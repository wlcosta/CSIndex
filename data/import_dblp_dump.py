#!/usr/bin/env python3
"""Build CSIndex's per-researcher DBLP cache from an official XML snapshot.

This is deliberately a source adapter only: it retains the existing researcher
PID list and emits the ``dblpperson``/``r`` structure consumed by csindexbr.py.
It does not classify papers or change any scoring configuration.
"""

import argparse
import csv
import gzip
import os
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import quoteattr

import xmltodict


RECORD_TYPES = {
    "article",
    "inproceedings",
    "proceedings",
    "book",
    "incollection",
    "phdthesis",
    "mastersthesis",
}


def author_pids(record):
    """Yield persistent DBLP PIDs attached to a bibliographic record."""
    authors = record.get("author", [])
    if not isinstance(authors, list):
        authors = [authors]
    for author in authors:
        if isinstance(author, dict) and author.get("@pid"):
            yield author["@pid"]


def author_names(record):
    """Yield DBLP's canonical or alias author strings from a record."""
    authors = record.get("author", [])
    if not isinstance(authors, list):
        authors = [authors]
    for author in authors:
        if isinstance(author, dict):
            author = author.get("#text")
        if isinstance(author, str):
            yield author


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", required=True, type=Path, help="official dblp-YYYY-MM-DD.xml.gz")
    parser.add_argument(
        "--researchers",
        type=Path,
        default=Path("all-researchers.csv"),
        help="CSV with name, department, PID (default: all-researchers.csv)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../cache/dblp"),
        help="directory for generated per-researcher XML cache files",
    )
    parser.add_argument(
        "--fallback-cache-zip",
        type=Path,
        help="previous DBLP cache archive, used only to resolve retired profile aliases",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.dump.is_file() or args.dump.stat().st_size < 1024 * 1024:
        raise SystemExit(f"missing or implausibly small DBLP dump: {args.dump}")
    if not args.researchers.is_file():
        raise SystemExit(f"missing researcher list: {args.researchers}")

    researchers = []
    with args.researchers.open(encoding="utf-8", newline="") as csv_file:
        for row in csv.reader(csv_file):
            if len(row) != 3 or not all(row):
                raise SystemExit(f"invalid researcher row: {row!r}")
            name, _, pid = row
            researchers.append((name, pid))

    pid_to_researchers = defaultdict(list)
    for name, pid in researchers:
        pid_to_researchers[pid].append(name)
    if len(pid_to_researchers) != len(researchers):
        raise SystemExit("researcher list contains duplicate DBLP PIDs")

    redirects = {}

    def handle_redirect(path, record):
        if not path or path[-1][0] != "www" or not isinstance(record, dict):
            return True
        key = record.get("@key", "")
        if not key.startswith("homepages/"):
            return True
        pid = key.removeprefix("homepages/")
        if pid not in pid_to_researchers:
            return True
        crossref = record.get("crossref")
        if isinstance(crossref, dict):
            crossref = crossref.get("#text")
        if isinstance(crossref, str) and crossref.startswith("homepages/"):
            redirects[pid] = crossref.removeprefix("homepages/")
        return True

    try:
        with gzip.open(args.dump, "rb") as dump_file:
            xmltodict.parse(dump_file, item_depth=2, item_callback=handle_redirect)
    except (OSError, ValueError, xmltodict.expat.ExpatError) as error:
        raise SystemExit(f"unable to parse DBLP XML dump: {error}") from error

    canonical_pid = {pid: redirects.get(pid, pid) for _, pid in researchers}
    canonical_pids = set(canonical_pid.values())
    for pid, target in sorted(redirects.items()):
        print(f"DBLP profile redirect: {pid} -> {target}")

    aliases_by_canonical_pid = defaultdict(set)

    def handle_profile(path, record):
        if not path or path[-1][0] != "www" or not isinstance(record, dict):
            return True
        key = record.get("@key", "")
        if not key.startswith("homepages/"):
            return True
        pid = key.removeprefix("homepages/")
        if pid not in canonical_pids:
            return True
        title = record.get("title")
        if isinstance(title, dict):
            title = title.get("#text")
        if title == "Home Page":
            aliases_by_canonical_pid[pid].update(author_names(record))
        return True

    try:
        with gzip.open(args.dump, "rb") as dump_file:
            xmltodict.parse(dump_file, item_depth=2, item_callback=handle_profile)
    except (OSError, ValueError, xmltodict.expat.ExpatError) as error:
        raise SystemExit(f"unable to parse DBLP XML dump: {error}") from error

    aliases_by_pid = defaultdict(set)
    for _, pid in researchers:
        aliases_by_pid[pid].update(aliases_by_canonical_pid[canonical_pid[pid]])
    missing_profiles = [pid for _, pid in researchers if not aliases_by_pid[pid]]
    if missing_profiles and args.fallback_cache_zip:
        if not args.fallback_cache_zip.is_file():
            raise SystemExit(f"missing fallback cache archive: {args.fallback_cache_zip}")
        names_by_pid = {pid: name for name, pid in researchers}
        with zipfile.ZipFile(args.fallback_cache_zip) as archive:
            for pid in missing_profiles:
                member = f"dblp/{names_by_pid[pid].replace(' ', '-')}.xml"
                try:
                    cached = xmltodict.parse(archive.read(member))
                except KeyError as error:
                    raise SystemExit(f"fallback cache has no entry for retired PID {pid}") from error
                person = cached.get("dblpperson", {}).get("person", {})
                aliases_by_pid[pid].update(author_names(person))
        missing_profiles = [pid for _, pid in researchers if not aliases_by_pid[pid]]
    if missing_profiles:
        raise SystemExit(
            f"dump did not provide Home Page aliases for {len(missing_profiles)} researcher PID(s) "
            f"({', '.join(missing_profiles)}); "
            "refusing to create a partial cache"
        )
    alias_to_pids = defaultdict(set)
    for pid, aliases in aliases_by_pid.items():
        for alias in aliases:
            alias_to_pids[alias].add(pid)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    temporary_files = {}
    publication_counts = defaultdict(int)
    try:
        for name, pid in researchers:
            slug = name.replace(" ", "-")
            destination = args.output_dir / f"{slug}.xml"
            handle = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", delete=False,
                dir=args.output_dir, prefix=f".{slug}.", suffix=".tmp"
            )
            handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            handle.write(f"<dblpperson name={quoteattr(name)} pid={quoteattr(pid)}>\n")
            temporary_files[pid] = (handle, Path(handle.name), destination)

        def handle_record(path, record):
            if not path or not isinstance(record, dict):
                return True
            record_type = path[-1][0]
            if record_type not in RECORD_TYPES:
                return True
            matched_pids = set()
            for author in author_names(record):
                matched_pids.update(alias_to_pids.get(author, ()))
            if not matched_pids:
                return True
            record_xml = xmltodict.unparse({record_type: record}, full_document=False)
            for pid in matched_pids:
                handle, _, _ = temporary_files[pid]
                handle.write("<r>")
                handle.write(record_xml)
                handle.write("</r>\n")
                publication_counts[pid] += 1
            return True

        try:
            with gzip.open(args.dump, "rb") as dump_file:
                xmltodict.parse(dump_file, item_depth=2, item_callback=handle_record)
        except (OSError, ValueError, xmltodict.expat.ExpatError) as error:
            raise SystemExit(f"unable to parse DBLP XML dump: {error}") from error

        missing = [pid for _, pid in researchers if publication_counts[pid] == 0]
        if missing and args.fallback_cache_zip:
            names_by_pid = {pid: name for name, pid in researchers}
            with zipfile.ZipFile(args.fallback_cache_zip) as archive:
                for pid in missing:
                    member = f"dblp/{names_by_pid[pid].replace(' ', '-')}.xml"
                    try:
                        fallback_xml = archive.read(member).decode("utf-8")
                    except KeyError as error:
                        raise SystemExit(f"fallback cache has no publication entry for PID {pid}") from error
                    try:
                        xmltodict.parse(fallback_xml)
                    except xmltodict.expat.ExpatError as error:
                        raise SystemExit(f"fallback cache is malformed for PID {pid}") from error
                    handle, temporary, _ = temporary_files[pid]
                    handle.close()
                    with temporary.open("w", encoding="utf-8", newline="") as fallback_file:
                        fallback_file.write(fallback_xml)
                    publication_counts[pid] = 1
                    print(f"WARNING: retained August cache for {pid} ({names_by_pid[pid]}); no September DBLP records")
            missing = [pid for _, pid in researchers if publication_counts[pid] == 0]
        if missing:
            names_by_pid = {pid: name for name, pid in researchers}
            missing_details = ", ".join(f"{pid} ({names_by_pid[pid]})" for pid in missing)
            raise SystemExit(
                f"dump produced no bibliographic records for {len(missing)} researcher PID(s) "
                f"({missing_details}); "
                "refusing to replace the cache"
            )

        for pid, (handle, temporary, destination) in temporary_files.items():
            if not handle.closed:
                handle.write("</dblpperson>\n")
                handle.close()
            if temporary.stat().st_size < 128:
                raise SystemExit(f"generated empty cache file for PID {pid}")
            os.replace(temporary, destination)
            print(f"{pid}: {publication_counts[pid]} records")
    except BaseException:
        for handle, temporary, _ in temporary_files.values():
            if not handle.closed:
                handle.close()
            temporary.unlink(missing_ok=True)
        raise

    print(f"Imported {sum(publication_counts.values())} records for {len(researchers)} researchers.")


if __name__ == "__main__":
    main()
