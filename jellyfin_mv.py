#!/usr/bin/env python3

"""
This module provides functionality for moving Video Files to specified Destination folders in
accordance with Jellyfin Folder Structure Conventions.
"""

import filecmp
import os
import re
import shutil
import subprocess
import sys
import termios
import textwrap
import time

from colorama import Fore

CACHE_FILE = "/tmp/jf-mv_last-selected.txt"

is_verbose = False
copy_source = False
total_files = -1
current_file = -1


def wrap_with_tabs(text, width, continuation_tabs=2):
    if len(text) <= width:
        return text
    wrapped = textwrap.wrap(
        text, width=width, break_long_words=True, break_on_hyphens=False
    )
    return ("\n" + "\t" * continuation_tabs).join(wrapped)


def set_stdin_echo(enabled):
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
            print_error_and_die("fzf: Please select a destination folder")

        # write back to file
        selected_title = fzf.stdout.strip().replace("/", "").split("\n")[-1]
        if not selected_title:
            print_error_and_die("No title selected")
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

        # copy file to target
        self.dest_file = os.path.join(dest, self.basename)
        self.dest_dir = dest
        # dst_file_output = "$JELLYFIN_SERIES_FOLDER" if self.is_series else "$JELLYFIN_MOVIE_FOLDER"
        # dst_file_output += "/" + re.sub(f"^{os.path.abspath(self.target)}/", "", os.path.abspath(dst_file))
        src_size = os.path.getsize(self.path)
        copied = 0
        chunk_size = 2**20  # 1MiB
        bar_width = 30
        txt_move_or_copy = "copying" if copy_source else "moving"
        term_width = shutil.get_terminal_size(fallback=(120, 24)).columns
        src_display = wrap_with_tabs(
            self.path,
            width=max(20, term_width - len(txt_move_or_copy) - 8),
            continuation_tabs=2,
        )
        dst_display = wrap_with_tabs(
            self.dest_file,
            width=max(20, term_width - 8),
            continuation_tabs=2,
        )
        print_info(
            f'{txt_move_or_copy}\t{Fore.MAGENTA}"{src_display}"{Fore.RESET}\n\tto\t{Fore.MAGENTA}"{dst_display}"{Fore.RESET}'
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
                    chunk = src.read(chunk_size)
                    if not chunk:
                        stop = True
                    dst.write(chunk)
                    copied += len(chunk)

                    if src_size > 0:
                        progress = copied / src_size
                        filled = int(progress * bar_width)
                        bar = "=" * filled + " " * (bar_width - filled)
                        elapsed = max(time.time() - t0, 1e-9)
                        speed_mib_s = (copied / 2**20) / elapsed

                        spacing = 4
                        color = Fore.GREEN if stop else Fore.RESET
                        txt_total_files = (
                            f"{Fore.BLUE}[{current_file}/{total_files}] "
                            if total_files > 1
                            else ""
                        )
                        line = (
                            f"{txt_total_files}"
                            f"{color}"
                            f"[{bar}] {progress * 100:.2f}%"
                            f"{" " * spacing}"
                            f"{Fore.RESET}"
                            f"{(copied/2**20):,.0f} / {(src_size/2**20):,.0f} MiB"
                            f"{" " * spacing}"
                            f"{speed_mib_s:5.1f} MiB/s"
                        )
                        print(f"\t{line}", end="\r", flush=True)
                    else:
                        print_error_and_die(f'File "{self.path}" is empty')

                    if stop:
                        break
            except KeyboardInterrupt:
                print()
                print_error_and_die("Keyboard Interrupt")
            finally:
                if old_stdin_attrs is not None:
                    termios.tcsetattr(
                        sys.stdin.fileno(), termios.TCSADRAIN, old_stdin_attrs
                    )
        shutil.copystat(self.path, self.dest_file)

        # remove src file if successfull
        if copy_source:
            print()
            return
        if filecmp.cmp(self.path, self.dest_file, shallow=False):
            os.remove(self.path)
        else:
            print_error_and_die(
                "Destination file and source file are different. Keeping source file."
            )
        print()

    def cleanup_trickplay(self):
        trickplay = os.path.splitext(self.dest_file)[0] + ".trickplay"
        if os.path.isdir(trickplay):
            print_info(f'removing {Fore.MAGENTA}"{trickplay}"{Fore.RESET}')
            shutil.rmtree(trickplay)

    def update_nfo(self):
        # TODO: Check if multiple Cuts of Movie
        nfo_file = os.path.splitext(self.dest_file)[0] + ".nfo" if self.is_series or self.is_extra else "movie.nfo"
        if os.path.isfile(nfo_file):
            # TODO: update <dateadded>
            pass

    def print_information(self):
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


def print_usage_and_die():
    print_error_and_die(f"Usage: {sys.argv[0]} <file> ...")


def parse_cmd_line_for_key(key):
    if "-" + key in sys.argv:
        sys.argv.remove("-" + key)
        return True
    return False


def print_info(msg, end="\n", flush=False):
    print(f"{Fore.BLUE}[INFO]:{Fore.RESET} {msg}", end=end, flush=flush)


def print_error_and_die(msg, end="\n", flush=False):
    print(f"{Fore.RED}[ERROR]:{Fore.RESET} {msg}", end=end, flush=flush)
    sys.exit(1)


# -------------------------------------------------------------------------- #

if __name__ == "__main__":
    cached_title = ""

    # Parse arguments
    if len(sys.argv) <= 1:
        print_usage_and_die()
    is_verbose = parse_cmd_line_for_key("v")
    copy_source = parse_cmd_line_for_key("c")
    files = sys.argv[1:]
    total_files = len(files)

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
            print_error_and_die("No destination folder set")
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

        # TODO: handle Extended/Cinematic Cuts

        # print info
        if is_verbose:
            video_file.print_information()

        # move to destination folder
        video_file.move()
        video_file.update_nfo()
        video_file.cleanup_trickplay()
