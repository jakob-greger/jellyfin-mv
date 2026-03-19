#!/usr/bin/env python3

"""
This module provides functionality for moving Video Files to specified Destination folders in
accordance with Jellyfin Folder Structure Conventions.
"""

import datetime
import filecmp
import os
import re
import shutil
import subprocess
import sys
import termios
import time
from threading import Thread

from colorama import Fore

CACHE_FILE = "/tmp/jf-mv_last-selected.txt"

# cmd line flags
is_verbose = False
copy_source = False
check_shallow = False
keep_trickplay = False
preserve_dateadded = False

total_files = -1
current_file = -1


def set_stdin_echo(enabled):
    # TODO: Make easier to use. Put try catch here
    if not sys.stdin.isatty():
        return None

    fd = sys.stdin.fileno()
    attrs = termios.tcgetattr(fd)
    new_attrs = attrs[:]
    if enabled:
        new_attrs[3] |= termios.ECHO
    else:
        new_attrs[3] &= ~termios.ECHO
    termios.tcsetattr(fd, termios.TCSADRAIN, new_attrs)
    return attrs


class MediaFile:
    def __init__(self, file_name):
        self.path = file_name
        self.basename = os.path.basename(file_name)
        self.is_series = False
        self.is_extra = False
        self.season = -1
        self.episode = -1
        self.title = ""
        self.target = ""

    def query_title(self, folder):
        # read tmp file containing the last selected series/movie
        last_movie = ""
        last_series = ""
        if os.path.isfile(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="UTF8") as f:
                last_movie = f.readline().strip().split("last_movie=")[-1]
                last_series = f.readline().strip().split("last_series=")[-1]
        last_selected = last_series if self.is_series else last_movie

        # Query movie/series inside destination folder using the last selected as default
        t = "Series" if self.is_series else "Movie"
        fzf = subprocess.run(
            f"""
                fd -t d -d 1 \
                | fzf --prompt='Choose {t} folder or type a new one: ' --height=40% --query='{last_selected}' --print-query
            """,
            cwd=folder,
            text=True,
            shell=True,
            capture_output=True,
            check=False,
        )
        if fzf.returncode == 130:
            print_error("fzf: Please select a destination folder")

        # write back to file
        selected_title = fzf.stdout.strip().replace("/", "").split("\n")[-1]
        if not selected_title:
            print_error("No title selected")
        with open(CACHE_FILE, "w", encoding="UTF8") as f:
            if self.is_series:
                f.write(f"last_movie={last_movie}\nlast_series={selected_title}")
            else:
                f.write(f"last_movie={selected_title}\nlast_series={last_series}")

        return selected_title

    def move(self):
        def rem_ignore(path):
            file = os.path.join(path, ".ignore")
            if os.path.isfile(file):
                os.remove(file)
                print_info(f'removed {Fore.MAGENTA}"{file}"')

        # create target folder if necessary
        dest = f"{self.target}/{self.title}"
        rem_ignore(dest)
        if self.is_series:
            dest += f"/Season {self.season}"
            rem_ignore(dest)
        if self.is_extra:
            dest += "/extras"
            rem_ignore(dest)
        if not os.path.isdir(dest):
            print_info(f'creating folder {Fore.MAGENTA}"{dest}"')
            os.makedirs(dest)

        # strip "extras-..."
        if self.is_extra:
            self.basename = re.sub("^extras-", "", self.basename, flags=re.IGNORECASE)
            if self.is_series:
                self.basename = re.sub(
                    r"^s\d+-", "", self.basename, flags=re.IGNORECASE
                )

        # Check for empty files
        self.dest_file = os.path.join(dest, self.basename)
        self.dest_dir = dest
        src_size = os.path.getsize(self.path)
        if src_size <= 0:
            print_warning(f'File "{self.path}" is empty. Skipping...')
            return 1

        # copy file to target
        copied = 0
        final_progress_line = ""
        chunk_size = 2**20  # 1MiB
        bar_width = 30
        txt_move_or_copy = "copying" if copy_source else "moving"
        print_info(
            f'{txt_move_or_copy}\t{Fore.MAGENTA}"{self.path}"{Fore.RESET}\n\tto\t{Fore.MAGENTA}"{self.dest_file}"{Fore.RESET}'
        )
        t0 = time.time()
        old_stdin_attrs = None
        try:
            old_stdin_attrs = set_stdin_echo(False)
        except termios.error:
            old_stdin_attrs = None
        with open(self.path, "rb") as src, open(self.dest_file, "wb") as dst:
            try:
                while True:
                    stop = False

                    # write chunk
                    chunk = src.read(chunk_size)
                    if not chunk:
                        stop = True
                    dst.write(chunk)
                    copied += len(chunk)

                    # progress bar
                    progress = copied / src_size
                    filled = int(progress * bar_width)
                    bar = "=" * filled + " " * (bar_width - filled)

                    # speed
                    elapsed = max(time.time() - t0, 1e-9)
                    speed_mib_s = (copied / 2**20) / elapsed

                    # output styling
                    spacing = 4
                    color = Fore.GREEN if stop else Fore.RESET
                    txt_total_files = (
                        f"{Fore.CYAN}[{current_file}/{total_files}] "
                        if total_files > 1
                        else ""
                    )
                    line = (
                        "\t"
                        f"{txt_total_files}"
                        f"{color}"
                        f"[{bar}] {progress * 100:.2f}%"
                        f"{" " * spacing}"
                        f"{Fore.RESET}"
                        f"{(copied/2**20):,.0f} / {(src_size/2**20):,.0f} MiB"
                        f"{" " * spacing}"
                        f"{speed_mib_s:5.1f} MiB/s"
                    )
                    final_progress_line = line
                    print(line, end="\r", flush=True)

                    # artificial do ... while to have the 100% shown in GREEN
                    if stop:
                        break

            except KeyboardInterrupt:
                # catch keyboard Interrupts
                print()
                print_error("Keyboard Interrupt")
            finally:
                # reset terminal attributes for stdin echo
                if old_stdin_attrs is not None:
                    fd = sys.stdin.fileno()
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_stdin_attrs)
                    termios.tcflush(fd, termios.TCIFLUSH)

        # copy file metadata
        shutil.copystat(self.path, self.dest_file)

        # remove src file if successfull
        sucess = True

        def check_files():
            nonlocal sucess
            sucess = filecmp.cmp(self.path, self.dest_file, shallow=False)


        if check_shallow:
            sucess = filecmp.cmp(self.path, self.dest_file, shallow=True)
        else:
            try:
                old_stdin_attrs = set_stdin_echo(False)
            except termios.error:
                old_stdin_attrs = None
            t = Thread(target=check_files)
            t.start()
            try:
                spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                frame = 0
                while t.is_alive():
                    print(
                        f"{final_progress_line}{" " * spacing}{spinner[frame]} Verifying files",
                        end="\r",
                        flush=True,
                    )
                    frame = (frame + 1) % len(spinner)
                    time.sleep(0.08)
                t.join()
            except KeyboardInterrupt:
                # catch keyboard Interrupts
                print()
                print_error("Keyboard Interrupt")
            finally:
                # reset terminal attributes for stdin echo
                if old_stdin_attrs is not None:
                    fd = sys.stdin.fileno()
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_stdin_attrs)
                    termios.tcflush(fd, termios.TCIFLUSH)

        if sucess:
            print(
                f"{final_progress_line}{" " * spacing}{Fore.GREEN}Files verified!{Fore.RESET}  "
            )
            return 0
        else:
            return -1

    def cleanup_trickplay(self):
        if keep_trickplay:
            return
        trickplay = os.path.splitext(self.dest_file)[0] + ".trickplay"
        if os.path.isdir(trickplay):
            print_info(f'removing {Fore.MAGENTA}"{trickplay}"{Fore.RESET}')
            shutil.rmtree(trickplay)

    def update_nfo(self):
        if preserve_dateadded:
            return
        # TODO: Check if multiple Cuts of Movie
        nfo_file = (
            os.path.splitext(self.dest_file)[0] + ".nfo"
            if self.is_series or self.is_extra
            else os.path.join(self.dest_dir, "movie.nfo")
        )
        if os.path.isfile(nfo_file):
            lines = []
            with open(nfo_file, "r") as f:
                lines = f.readlines()

            with open(nfo_file, "w") as f:
                for line in lines:
                    if "<dateadded>" in line:
                        current_time = str(
                            datetime.datetime.now(datetime.timezone.utc)
                        ).split(".")[0]
                        line = re.sub(
                            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", current_time, line
                        )
                        f.write(line)
                        print_info(
                            f'{Fore.MAGENTA}<dateadded>{Fore.RESET} in {Fore.MAGENTA}"{os.path.basename(nfo_file)}"{Fore.RESET} '
                            f'updated to {Fore.MAGENTA}"{current_time}"{Fore.RESET}'
                        )
                    else:
                        f.write(line)

    def handle_special_cuts(self):
        # TODO: handle Extended/Cinematic Cuts
        pass

    def print_metadata(self):
        print_info('Fileinformation for "{}"'.format(self.basename))
        print(f"\t- Title: {self.title}")
        if self.is_extra:
            if self.is_series:
                print("\t- series-extra")
            else:
                print("\t- movie-extra")

        if self.is_series:
            print(f"\t- Season {self.season}")
            if not self.is_extra:
                print(f"\t- Episode {self.episode}")


def parse_file_name(file_name):
    res = MediaFile(file_name)
    res.path = file_name
    base_name = re.split("/", file_name)[-1]

    # is extra
    if re.search(r"^extras-*", base_name, flags=re.IGNORECASE):
        res.is_extra = True
        base_name = re.split(r"-", base_name, maxsplit=1)[1]

    # is series extra
    if res.is_extra and re.search(r"^s\d{2}", base_name, flags=re.IGNORECASE):
        res.is_series = True
        txt = re.split("-", base_name, maxsplit=1)
        res.season = int(re.split(r"^s", txt[0], maxsplit=1, flags=re.IGNORECASE)[1])
        base_name = txt[1]

    # is series episode
    if not res.is_extra and re.search(r"^s\d+e\d+", base_name, flags=re.IGNORECASE):
        res.is_series = True
        match = re.search(r"^s(\d+)e(\d+)", base_name, flags=re.IGNORECASE)
        if match:
            res.season = int(match.group(1))
            res.episode = int(match.group(2))

    return res


def print_help():
    print(
        f"{Fore.YELLOW}Usage:{Fore.RESET}\t{Fore.MAGENTA}{sys.argv[0]}{Fore.RESET} [OPTION]... FILE..."
    )
    print(
        f"\n{Fore.YELLOW}Desc:{Fore.RESET}"
        "\tMove Video Files to specified Destination folders in accordance with Jellyfin Folder Structure Conventions.\n"
        "\tSet the Destination Folders using "
        f"{Fore.CYAN}$JELLYFIN_MOVIE_FOLDER{Fore.RESET} and "
        f"{Fore.CYAN}$JELLYFIN_SERIES_FOLDER{Fore.RESET}.\n"
    )
    print(
        f"{Fore.YELLOW}Options:{Fore.RESET}\n"
        f"\t{Fore.CYAN}-h{Fore.RESET}\tview help\n"
        f"\t{Fore.CYAN}-v{Fore.RESET}\tverbose\n"
        f"\t{Fore.CYAN}-c{Fore.RESET}\tkeep source file\n"
        f"\t{Fore.CYAN}-s{Fore.RESET}\tshallow file verification\n"
        f"\t{Fore.CYAN}-t{Fore.RESET}\tkeep FILE.trickplay\n"
        f"\t{Fore.CYAN}-d{Fore.RESET}\tpreserve <dateadded> in movie/episode metadata\n"
    )
    print(
        f"Full documentation available at: {Fore.MAGENTA}<https://github.com/jakob-greger/jellyfin-mv>{Fore.RESET}"
    )


def parse_cmd_line():
    global is_verbose, copy_source, check_shallow, keep_trickplay, preserve_dateadded
    res = []
    for arg in sys.argv:
        # ignore program name
        if arg == sys.argv[0]:
            continue
        # parse flags
        if arg.startswith("-"):
            flags = arg[1:]
            for flag in flags:
                match flag:
                    case "h":
                        print_help()
                        sys.exit(0)
                    case "v":
                        is_verbose = True
                    case "c":
                        copy_source = True
                    case "s":
                        check_shallow = True
                    case "t":
                        keep_trickplay = True
                    case "d":
                        preserve_dateadded = True
                    case "-":
                        continue
                    case _:
                        print_error(f"Unrecognized flag '-{flag}'.", die=False)
                        print_help()
                        sys.exit(1)
        # append video to result
        else:
            res.append(arg)
    return res


def print_info(msg, end="\n", flush=False):
    print(f"{Fore.CYAN}[INFO]:{Fore.RESET} {msg}", end=end, flush=flush)


def print_error(msg, end="\n", flush=False, die=True):
    print(f"{Fore.RED}[ERROR]:{Fore.RESET} {msg}", end=end, flush=flush)
    if die:
        sys.exit(1)


def print_warning(msg, end="\n", flush=False):
    print(f"{Fore.YELLOW}[WARNING]:{Fore.RESET} {msg}", end=end, flush=flush)


# -------------------------------------------------------------------------- #

if __name__ == "__main__":
    cached_title = ""

    # Parse arguments
    files = parse_cmd_line()
    total_files = len(files)
    if total_files <= 0:
        print_error("No files provided", die=False)
        print_help()
        sys.exit(1)

    # get destination folders
    movie_folder = os.environ.get("JELLYFIN_MOVIE_FOLDER")
    series_folder = os.environ.get("JELLYFIN_SERIES_FOLDER")

    # Process files
    for idx, file in enumerate(files):
        current_file = idx + 1

        video_file = parse_file_name(file)

        # check destination folder
        dest_folder = series_folder if video_file.is_series else movie_folder
        if not dest_folder:
            print_error("No destination folder set")
        else:
            video_file.target = dest_folder

        # extract title and cache for all following episodes or extras
        if cached_title and (video_file.is_series or video_file.is_extra):
            video_file.title = cached_title
        else:
            if not video_file.is_extra and not video_file.is_series:
                title_ext = video_file.path.split("/")[-1]
                idx = title_ext.rfind(".")
                cached_title = video_file.title = title_ext[:idx]
            else:
                cached_title = video_file.title = video_file.query_title(dest_folder)

        # Extended Cut and Cinematic Cut should be in the same movie folder
        video_file.handle_special_cuts()

        # print info
        if is_verbose:
            video_file.print_metadata()

        # move to destination folder
        ret = video_file.move()
        if ret == 0:
            pass
        elif ret == -1:
            print_error(
                "Source and destination files differ. Continuing with next file!"
            )
            continue

        video_file.update_nfo()
        video_file.cleanup_trickplay()
