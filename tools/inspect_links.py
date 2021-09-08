#!/usr/bin/python3

"""
Inspect a set of markdown files, and warn if there are:
- duplicate links
- malformed links
"""

import argparse
import bs4
import logging
import markdown
import os
import re
import sys
import urllib

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class Warnings:
    """ A singleton object for gathering warnings to be printed later. """

    def __init__(self):
        self.warnings = []

    def warn(self, msg):
        self.warnings.append(msg)

    def get(self):
        return self.warnings


# The singleton object that gathers warnings, for later reporting.
warnings = Warnings()

# A regex that matches filenames to inspect.
RE_FILENAME = re.compile(r'\d\d\d\d-\d\d-\d\d-this-week-in-rust.md')

# A block-list of tracking parameters
TRACKING_PARAMETERS = set([
    'utm_source',
    'utm_campaign',
    'utm_medium',
    'utm_content',
])

# A list of section titles that will trigger duplicate-tag detection.
STRICT_TITLES = [
    'project/tooling updates',
    'observations/thoughts',
    'rust walkthroughs',
    'miscellaneous',
]


def is_strict_title(title):
    """ Return True if this title is one that needs strict checks. """
    title = str(title)
    # .lower() doesn't necessarily handle unicode in a robust way,
    # but the set of strings we care about is tiny, and use only ascii.
    return title.lower() in STRICT_TITLES


def extract_links(html):
    """ Return a list of links from this file.

    Links will only be returned if they are within a section deemed "strict".
    This allows us to ignore links that are deliberately repeated (to this
    github repo and twitter account, for example).

    Side-effects:
    - If links are malformed, warnings may be recorded. See `parse_url`
      for details.

    """
    strict_mode = False
    tags = ['a', 'h1', 'h2', 'h3', 'h4']
    urls = []
    for tag in bs4.BeautifulSoup(html, 'html.parser').find_all(tags):
        if tag.name == 'a':
            link = tag.get('href')
            LOG.debug(f'found link tag: {link}')
            if strict_mode:
                trimmed_url = parse_url(link)
                urls.append(trimmed_url)
        else:
            # This is the title of a section. If this title is "strict",
            # we will check for any duplicate links inside it.
            strict_mode = is_strict_title(tag.string)
            LOG.debug(f'found heading tag: {tag} (strict={strict_mode})')

    return urls


def scrub_parameters(url, query):
    """ Strip tracking parameters from the URL """
    query_dict = urllib.parse.parse_qs(query)

    filtered_dict = {}
    found_tracking = []
    for k, v in query_dict.items():
        if k in TRACKING_PARAMETERS:
            found_tracking.append(k)
        else:
            filtered_dict[k] = v

    # Store a warning if
    if found_tracking:
        warnings.warn(f'found tracking parameters on {url}: {found_tracking}')

    # If there are no query parameters left, return the empty string.
    if not filtered_dict:
        return ''

    # Re-encode remaining URL paramaters
    return urllib.parse.urlencode(filtered_dict, doseq=True)


def parse_url(link):
    """ Parse a URL and return it in a stripped-down form.

    This will strip HTTP parameters and anchors (in an effort to better
    detect duplicate URLs). However, as this would break some common URLs
    we don't strip parameters that are on the KEEP_PARAMETERS list.

    Side-effects:
    - If a link does not have a recognized protocol, we will
      record a warning.
    """
    parsed_url = urllib.parse.urlsplit(link)
    if parsed_url.scheme not in ('mailto', 'http', 'https'):
        warnings.warn(f'possibly malformed link: {link}')

    # If there are query parameters present, give them a cleanup pass to remove irrelevant ones.
    query = parsed_url.query
    if query:
        LOG.debug(f'{parsed_url.geturl()} found query parameters: {query}')
        query = scrub_parameters(link, query)
        if query:
            LOG.debug(
                f'{parsed_url.geturl()} keeping query parameters: {query}')

    # Re-constitute the URL with the reduced set of query parameters.
    (sch, loc, path, _, frag) = parsed_url
    reconstituted = urllib.parse.urlunsplit((sch, loc, path, query, frag))
    if reconstituted != link:
        LOG.debug(f'reconstituted: {reconstituted}')
        warnings.warn(f'link can be simplified: {link} -> {reconstituted}')
    return reconstituted


def inspect_file(filename):
    LOG.info(f'inspecting file {filename}')
    md_text = open(filename).read()
    html = markdown.markdown(md_text)
    links = extract_links(html)
    LOG.debug(f'examining {len(links)} links')
    return links


def get_recent_files(dir, count):
    """ return a list of the N most recent markdown files in `dir`.

    We assume the files are named "YYYY-MM-DD-this-week-in-rust-md".
    """
    LOG.debug(f'searching for {count} recent files in "{dir}"')
    listing = os.listdir(path=dir)
    if not listing:
        raise Exception(f'No files found in {dir}')
    listing = list(filter(RE_FILENAME.match, listing))
    if not listing:
        raise Exception(f'No matching files found in {dir}')
    listing.sort()
    listing = listing[-count:]
    LOG.info(f'recent files: {listing}')
    listing = [os.path.join(dir, f) for f in listing]
    return listing


def inspect_files(file_list):
    """ Inspect a set of files, storing warnings about duplicate links. """
    linkset = {}

    for file in file_list:
        links = inspect_file(file)
        LOG.debug(f'found links: {links}')
        for link in links:
            collision = linkset.get(link)
            if collision:
                warnings.warn(
                    f"possible duplicate link {link} in file {file} (also found in {collision}")
            else:
                linkset[link] = file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', default='content',
                        help="Directory path to inspect")
    parser.add_argument('--num-recent', default=5, type=int,
                        help="Number of recent files to inspect")
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    if args.debug:
        LOG.setLevel(logging.DEBUG)
    LOG.debug(f'command-line arguments: {args}')
    file_list = get_recent_files(args.path, args.num_recent)
    inspect_files(file_list)


def setup_logging():
    log_stderr = logging.StreamHandler()
    logging.getLogger('').addHandler(log_stderr)


if __name__ == "__main__":
    setup_logging()
    main()

    warns = warnings.get()
    if warns:
        print("warnings exist:")
        for w in warns:
            print(w)
        sys.exit(1)
    else:
        print("everything is ok!")
