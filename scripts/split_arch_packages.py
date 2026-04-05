#!/usr/bin/env python3

import re
import shutil
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path


OFFICIAL_REPOS = {"core", "extra", "multilib"}


def run_command(cmd):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout


def pick_aur_helper():
    if shutil.which("paru"):
        return "paru"
    if shutil.which("yay"):
        return "yay"
    raise RuntimeError("Neither 'paru' nor 'yay' is installed.")


def repo_of_pkg(pkg):
    code, output = run_command(["pacman", "-Si", "--", pkg])
    if code != 0:
        return None

    for line in output.splitlines():
        if line.startswith("Repository"):
            _, value = line.split(":", 1)
            return value.strip()

    return None


def is_in_aur(pkg, aur_helper):
    code, _ = run_command([aur_helper, "-Si", "--aur", "--", pkg])
    return code == 0


def add_pkg(groups, heading, value):
    groups.setdefault(heading, [])
    groups[heading].append(value)


def write_grouped_markdown(path, groups):
    with path.open("w", encoding="utf-8") as f:
        first = True
        for heading, items in groups.items():
            if not items:
                continue

            if not first:
                f.write("\n")

            if heading is not None:
                f.write(f"{heading}\n")

            for item in items:
                f.write(f"{item}\n")

            first = False


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("packages.md")

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        aur_helper = pick_aur_helper()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    heading_re = re.compile(r"^#{1,6}\s+.+$")
    bullet_re = re.compile(
        r"""
        ^
        (?P<prefix>\s*[-*]\s+(?:\[[ xX]\]\s+)?)
        (?P<pkg>[A-Za-z0-9@._+-]+)
        (?P<rest>\s*(?:\#.*)?)
        $
        """,
        re.VERBOSE,
    )

    official = OrderedDict()
    chaotic = OrderedDict()
    aur = OrderedDict()
    unknown = OrderedDict()

    current_heading = None

    for line in input_path.read_text(encoding="utf-8").splitlines():
        if heading_re.match(line):
            current_heading = line
            for group in (official, chaotic, aur, unknown):
                group.setdefault(current_heading, [])
            continue

        match = bullet_re.match(line)
        if not match:
            continue

        prefix = match.group("prefix")
        pkg = match.group("pkg")
        rest = match.group("rest") or ""
        rendered = f"{prefix}{pkg}{rest}"

        repo = repo_of_pkg(pkg)

        if repo in OFFICIAL_REPOS:
            add_pkg(official, current_heading, rendered)
        elif repo == "chaotic-aur":
            add_pkg(chaotic, current_heading, rendered)
        elif repo is None:
            if is_in_aur(pkg, aur_helper):
                add_pkg(aur, current_heading, rendered)
            else:
                add_pkg(unknown, current_heading, rendered)
        else:
            add_pkg(unknown, current_heading, f"{prefix}{pkg}{rest}  # repo: {repo}")

    write_grouped_markdown(Path("official.md"), official)
    write_grouped_markdown(Path("chaotic-aur.md"), chaotic)
    write_grouped_markdown(Path("aur.md"), aur)
    write_grouped_markdown(Path("unknown.md"), unknown)

    print("Wrote official.md, chaotic-aur.md, aur.md, unknown.md")


if __name__ == "__main__":
    main()
