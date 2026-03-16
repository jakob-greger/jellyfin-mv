"""
This module provides functionality for moving Video Files to specified Destination folders in
accordance with Jellyfin Folder Structure Conventions.
"""

import os
import sys
import re
import subprocess

CACHE_FILE = "/tmp/jf-mv_last-selected.txt"

is_verbose = False

class MediaFile:
    def __init__(self, file_name=""):
        self.file_name = file_name
        self.is_series = False
        self.is_extra = False
        self.season = -1
        self.episode = -1
        self.title = ""
        self.path = ""
        self.target = ""

    def query_title(self, folder):
        # read tmp file containing the last selected series/movie
        last_movie = ""
        last_series = ""
        with open(CACHE_FILE, "r", encoding="ASCII") as f:
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
            check=False
        )
        if fzf.returncode == 130:
            print("[ERROR]: fzf: Please select a destination directory")
            sys.exit(1)

        # write back to file
        selected_title = fzf.stdout.strip().replace("/", "").split("\n")[-1]
        if not selected_title:
            print("[ERROR]: No title selected")
            sys.exit(1)
        with open(CACHE_FILE, "w", encoding="ASCII") as f:
            if self.is_series:
                f.write(f"last_movie={last_movie}\nlast_series={selected_title}")
            else:
                f.write(f"last_movie={selected_title}\nlast_series={last_series}")

        return selected_title

    def move(self):
        # create target folder if necessary
        if self.title not in os.listdir(self.target):
            dest = f"{self.target}/{self.title}"
            print(f"[INFO]: creating folder {dest}")
            os.mkdir(dest)

    def print_information(self):
        print(f"[INFO]: Fileinformation for \"{self.file_name}\"")
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
    if re.search(r"^extras-*", base_name):
        res.is_extra = True
        base_name = re.split(r"-", base_name, maxsplit=1)[1]

    # is series extra
    if res.is_extra and re.search(r"^s\d{2}", base_name):
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
    print(f"[USAGE]: {sys.argv[0]} [files]")
    sys.exit(1)

def parse_cmd_line_for_key(key):
    if key in sys.argv:
        sys.argv.remove(key)
        return True
    return False

# -------------------------------------------------------------------------- #

if __name__ == "__main__":
    cached_title = ""

    # Parse arguments
    if len(sys.argv) <= 1:
        print_usage_and_die()
    is_verbose = parse_cmd_line_for_key("-v")
    files = sys.argv[1:]

    # get destination folders
    movie_folder = os.environ.get("JELLYFIN_MOVIE_FOLDER")
    series_folder = os.environ.get("JELLYFIN_SERIES_FOLDER")

    # Process files
    for file in files:
        video_file = parse_file_name(file)

        # check destination folder
        dest_folder = series_folder if video_file.is_series else movie_folder
        if not dest_folder:
            print("[Error]: No destination folder set")
            sys.exit(1)
        video_file.target = dest_folder

        # extract title and cache for all following files
        if cached_title:
            video_file.title = cached_title
        else:
            if not video_file.is_extra and not video_file.is_series:
                title_ext = video_file.path.split("/")[-1]
                idx = title_ext.rfind(".")
                cached_title = video_file.title = title_ext[:idx]
            else:
                cached_title = video_file.title = video_file.query_title(dest_folder)

        # print info
        if is_verbose:
            video_file.print_information()

        # move to destination folder
        video_file.move()
