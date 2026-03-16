"""
This module provides functionality for moving Video Files to specified Destination folders in
accordance with Jellyfin Folder Structure Conventions.
"""

import os
import sys
import re
import subprocess

CACHE_FILE = "/tmp/jf-mv_last-selected.txt"

class VideoFile:
    """
    Represents a VideoFile with certain properties

    Attributes:
        file_name (str): File-basename
        is_series (bool): whether the file is a series or a movie
        is_extra (bool): whether the file is an extra
        season (int): the seasonnumber
        episode (int): the episode number
        title (str): the title of the series/movie as found in the destination folder
    """

    def __init__(self, file_name=""):
        self.file_name = file_name
        self.is_series = False
        self.is_extra = False
        self.season = -1
        self.episode = -1
        self.title = ""

    def query_title(self, folder):
        """
        Queries the title of the movie/series that already exists in the given folder

        Args:
            folder (str): folder where to search

        Returns:
            str: Folder basename
        """
        # check if destination folder is set
        if not folder:
            print("[ERROR]: No destination folder set!")
            sys.exit(1)

        # read tmp file containing the last selected series/movie
        last_movie = ""
        last_series = ""
        with open(CACHE_FILE, "w+", encoding="ASCII") as f:
            last_movie = f.readline().strip()
            last_series = f.readline().strip()
        last_selected = last_series if self.is_series else last_movie

        # Query movie/series inside destination folder using the last selected as default
        t = "Series" if self.is_series else "Movie"
        res = subprocess.run(
            f"""
                fd -t d -d 1 \
                | fzf --prompt='Choose {t} folder ' --height=40% --query='{last_selected}'
            """,
            cwd=folder,
            text=True,
            shell=True,
            capture_output=True,
            check=False
        )
        if res.returncode == 130:
            print("[ERROR]: fzf: Please select a destination directory")
            sys.exit(1)
        self.title = res.stdout.strip()

        return res.stdout.strip()

    def print_information(self):
        """Prints all the relevant information of this instance"""
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
    """
    Parses given file_name for is_series

    Args:
        file_name (int): the name of the file

    Returns:
        VideoFile: The File object containint the set attributes
    """
    res = VideoFile(file_name)
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

def print_usage():
    """Prints correct usage of program"""
    print(f"[USAGE]: {sys.argv[0]} [files]")

# -------------------------------------------------------------------------- #

if __name__ == "__main__":
    cached_title = ""

    # Parse arguments
    files = sys.argv[1:]
    if len(files) == 0:
        print_usage()

    # get destination folders
    movie_folder = os.environ.get("JELLYFIN_MOVIE_FOLDER")
    series_folder = os.environ.get("JELLYFIN_SERIES_FOLDER")

    # Process files
    for file in files:
        video_file = parse_file_name(file)

        # cache title for all following files
        if not cached_title:
            dest_folder = series_folder if video_file.is_series else movie_folder
            cached_title = video_file.query_title(dest_folder)

        #TODO: implement file handling
        video_file.print_information()
