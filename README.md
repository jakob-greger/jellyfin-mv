# jellyfin-mv

## What is it for?
Easilly transfer media files (Movies and TV Shows) to their dedicated folders for jellyfin.

See also:
[jellyfin.org/docs/general/server/media/movies](https://jellyfin.org/docs/general/server/media/movies)
and
[jellyfin.org/docs/general/server/media/shows](https://jellyfin.org/docs/general/server/media/shows)
for file naming

## Supported Formats:
- Movies: e.g. `Interstellar (2014) [tmdbid-157336].mkv`
    - Special Cuts: e.g. `The_Lord_of_the_Rings_-_The_Return_of_the_King (2004) [tmdbid-122] - Extended Cut.mkv`
- TV Shows: e.g. `S01E01.mkv` (Selection of TV Show with fzf unless previously cached)
- Extras:
    - for movie-extras: e.g. `extras-Making of Oppenheimer.mp4` (Selection of Movie with fzf unless previously cached)
    - for tv-show-extras: e.g. `extras-s06-Inside Episode 13 - Saul Gone.mp4` (Selection of TV Show with fzf unless previously cached)

## Additional Features:
- removal of any `.ignore` files in the target directories
- removal of already present `.trickplay` folders to let jellyfin automatically refresh those
- updating of `<dateadded>` metadata field, to let jellyfin know, this content is new (only works when the metadata is in the same folder as `.nfo` file)
- beautiful output with progress bars, etc.

## Installation:
### Requirements:
- python
- fzf

```
git clone https://github.com/jakob-greger/jellyfin-mv.git
cd jellyfin-mv

chmod +x jellyfin_mv.py
ln -rs jellyfin_mv.py ~/.local/bin/jfmv
```

## Usage:
```
jfmv [OPTION]... FILE...
```

Note: Since the TV-Show or movie title you specify using fzf will be cached, you should handle different shows or extras belonging to different movies seperately.

### Options
- `-c`  keep source file (copy instead of moving)
- `-d`  preserve `<dateadded>` if already present for target file
- `-h`  view help
- `-i`  preserve `.ignore` files in target folders
- `-m`  Only print parsed metadata
- `-s`  only a shallow file verification at the end of the copy instead of a deep one
- `-t`  keep `.trickplay`-folders

### Example:
```
jfmv "Star_Trek_IV_-_The_Voyage_Home (1986) [tmdbid-168].mkv" "extras-Making of.mkv" "extras-interview.mkv" "extras-VFX.mkv"
jfmv "S04E*.mkv" "extras-s04-Gag Reel.mkv"
jfmv "Blade Runner.mkv" "Blade Runner 2049.mkv"
```

