"""
A web search server for ParlAI, including Blenderbot2.
See README.md
"""
import http.server
import json
import re
from typing import *
import urllib.parse

import bs4
import chardet
import fire
import html2text
import googlesearch
import parlai.agents.rag.retrieve_api
import rich
import rich.markup
import requests


print = rich.print

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8080


def _parse_host(host: str) -> Tuple[str, int]:
    splitted = host.split(":")
    hostname = splitted[0]
    port = splitted[1] if len(splitted) > 1 else _DEFAULT_PORT
    return hostname, int(port)


def _get_and_parse(url: str) -> Dict[str, str]:

    try:
        resp = requests.get(url)
    except requests.exceptions.RequestException as e:
        print(f"[!] {e} for url {url}")
        return None
    else:
        resp.encoding = resp.apparent_encoding
        page = resp.text
    
    ###########################################################################
    # Prepare the title
    ###########################################################################
    output_dict = dict(title="", content="", url=url)
    soup = bs4.BeautifulSoup(page, features="lxml")
    pre_rendered = soup.find("title")
    output_dict["title"] = (
        pre_rendered.renderContents().decode() if pre_rendered else ""
    )
    
    output_dict["title"] = (
        output_dict["title"].replace("\n", "").replace("\r", "")
    )

    ###########################################################################
    # Prepare the content
    ###########################################################################
    text_maker = html2text.HTML2Text()
    text_maker.ignore_links = True
    text_maker.ignore_tables = True
    text_maker.ignore_images = True
    text_maker.ignore_emphasis = True
    text_maker.single_line = True
    output_dict["content"] = text_maker.handle(page).strip()

    return output_dict


class SearchABC(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        #######################################################################
        # Prepare and Parse
        #######################################################################
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)

        # Figure out the encoding
        if "charset=" in self.headers["Content-Type"]:
            charset = re.match(r".*charset=([\w_\-]+)\b.*", self.headers["Content-Type"]).group(1)
        else:
            detector = chardet.UniversalDetector()
            detector.feed(post_data)
            detector.close()
            charset = detector.result["encoding"]

        post_data = post_data.decode(charset)
        parsed = urllib.parse.parse_qs(post_data)

        for v in parsed.values():
            assert len(v) == 1, len(v)
        parsed = {k: v[0] for k, v in parsed.items()}

        #######################################################################
        # Search, get the pages and parse the content of the pages
        #######################################################################
        print(f"\n[bold]Received query:[/] {parsed}")
        n = int(parsed["n"])
        q = parsed["q"]

        # Over query a little bit in case we find useless URLs
        content = []
        dupe_detection_set = set()
        
        # Search until we have n valid entries
        for url in self.search(q=q, n=n):
            if len(content) >= n:
                break

            # Get the content of the pages and parse it
            maybe_content = _get_and_parse(url)

            # Check that getting the content didn't fail
            reason_empty_response = maybe_content is None
            if (not reason_empty_response):
                reason_content_empty = (
                    maybe_content["content"] is None
                    or len(maybe_content["content"]) == 0
                )
                reason_already_seen_content = (
                    maybe_content["content"] in dupe_detection_set
                )
            reasons = dict(
                reason_empty_response=reason_empty_response,
                reason_content_empty=reason_content_empty,
                reason_already_seen_content=reason_already_seen_content,
            )

            if not any(reasons.values()):
                ###############################################################
                # Log the entry
                ###############################################################
                title_str = (
                    f"`{rich.markup.escape(maybe_content['title'])}`"
                    if maybe_content["title"]
                    else "<No Title>"
                )
                print(
                    " [green]>[/] Result:",
                    f"Title: {title_str}",
                    f"url: {rich.markup.escape(maybe_content['url'])}",
                    f"Content: {len(maybe_content['content'])}",
                )
                dupe_detection_set.add(maybe_content["content"])
                content.append(maybe_content)
                if len(content) >= n:
                    break

            else:
                ###############################################################
                # Log why it failed
                ###############################################################
                reason_string = ", ".join(
                    {
                        reason_name
                        for reason_name, whether_failed in reasons.items()
                        if whether_failed
                    }
                )
                print(f" x Excluding an URL because `{reason_string}`: `{url}`")

        ###############################################################
        # Prepare the answer and send it
        ###############################################################
        content = content[:n]  
        output = json.dumps(dict(response=content)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", len(output))
        self.end_headers()
        self.wfile.write(output)

    def search(self, q: str, n: int) -> Generator[str, None, None]:
        return NotImplemented(
            "Search is an abstract base class, not meant to be directly "
            "instantiated. You should instantiate a derived class like "
            "GoogleSearch."
        )


class GoogleSearchServer(SearchABC):
    def search(self, q: str, n: int) -> Generator[str, None, None]:
        return googlesearch.search(q, num=n, stop=None)


class Application:
    def serve(self, host: str = _DEFAULT_HOST) -> NoReturn:
        host, port = _parse_host(host)

        with http.server.ThreadingHTTPServer(
            (host, int(port)), GoogleSearchServer
        ) as server:
            print("Serving forever.")
            server.serve_forever()

    def test_parser(self, url):
        print(_get_and_parse(url))

    def test_server(self, query, n, host=_DEFAULT_HOST):
        host, port = _parse_host(host)

        print(f"Query: `{query}`")
        print(f"n: {n}")

        retriever = parlai.agents.rag.retrieve_api.SearchEngineRetriever(
            dict(
                search_server=f"{host}:{port}",
                skip_retrieval_token=False,
            )
        )
        print("Retrieving one.")
        print(retriever._retrieve_single(query, n))
        print("Done.")


if __name__ == "__main__":
    fire.Fire(Application)
