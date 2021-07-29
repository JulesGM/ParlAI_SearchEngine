"""
A web search server for ParlAI, including Blenderbot2.
See README.md
"""
import html
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
_DELAY_SEARCH = 1.0  # Making this too low will get you IP banned
_STYLE_GOOD = "[green]"
_STYLE_SKIP = ""
_CLOSE_STYLE_GOOD = "[/]" if _STYLE_GOOD else ""
_CLOSE_STYLE_SKIP = "[/]" if _STYLE_SKIP else ""
_requests_get_timeout = 5 # seconds
_strip_html_menus = False 
_max_text_bytes = None  

# To get a free Bing Subscription Key go here:
#    https://www.microsoft.com/en-us/bing/apis/bing-entity-search-api
_use_bing = False # Use Bing instead of Google Search Engine

_use_bing_description_only = False # short but 10X faster

# Bing Search API documentation:
# https://docs.microsoft.com/en-us/bing/search-apis/bing-web-search/reference/query-parameters

def _parse_host(host: str) -> Tuple[str, int]:
    """ Parse the host string.
    Should be in the format HOSTNAME:PORT.
    Example: 0.0.0.0:8080
    """
    splitted = host.split(":")
    hostname = splitted[0]
    port = splitted[1] if len(splitted) > 1 else _DEFAULT_PORT
    return hostname, int(port)


def _get_and_parse(url: str) -> Dict[str, str]:
    """ Download a webpage and parse it. """

    global _requests_get_timeout

    try:
        resp = requests.get(url, timeout=_requests_get_timeout)
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
        html.unescape(pre_rendered.renderContents().decode()) if pre_rendered else ""
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
    output_dict["content"] = html.unescape(text_maker.handle(page).strip())

    return output_dict


class SearchABC(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        global _strip_html_menus, _max_text_bytes, _use_bing, _use_bing_description_only

        """ Handle POST requests from the client. (All requests are POST) """

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
        if _use_bing:
            search_engine = "Bing"
        else:
            search_engine = "Google"

        print(f"\n[bold]Received query:[/] {parsed}, using {search_engine} search engine and using bing link descriptions only {_use_bing_description_only}")

        n = int(parsed["n"])
        q = parsed["q"]

        # Over query a little bit in case we find useless URLs
        content = []
        dupe_detection_set = set()

        urls = []
        if _use_bing:
            results = self.search_bing(q, n, ["News", "Entities", "Places", "Webpages"],
                _use_bing_description_only)

            if _use_bing_description_only:
                content = results
            else:
                urls = results
        else:
            urls = self.search(q=q, n=n)

        # Only execute loop to fetch each URL if urls returned
        for url in urls:
            if len(content) >= n:
                break

            # Get the content of the pages and parse it
            maybe_content = _get_and_parse(url)

            # Check that getting the content didn't fail
            reason_empty_response = maybe_content is None
            if not reason_empty_response:
                reason_content_empty = (
                    maybe_content["content"] is None
                    or len(maybe_content["content"]) == 0
                )
                reason_already_seen_content = (
                    maybe_content["content"] in dupe_detection_set
                )
            else:
                reason_content_empty = False
                reason_already_seen_content = False

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
                    f" {_STYLE_GOOD}>{_CLOSE_STYLE_GOOD} Result: Title: {title_str}\n"
                    f"   {rich.markup.escape(maybe_content['url'])}"
                    # f"Content: {len(maybe_content['content'])}",
                )

                # Strip out all lines starting with "* " usually menu items
                if _strip_html_menus:
                    print("Stripping HTML menus")
                    new_content = ""
                    for line in maybe_content['content'].splitlines():
                        x = re.findall("^[\s]*\\* ", line)
                        if not x or len(line) > 50:
                            new_content += line + "\n"

                    maybe_content['content'] = new_content
                else:
                    print("Not stripping HTML menus")

                # Truncate text
                maybe_content['content'] = maybe_content['content'][:_max_text_bytes]

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
                print(f" {_STYLE_SKIP}x{_CLOSE_STYLE_SKIP} Excluding an URL because `{_STYLE_SKIP}{reason_string}{_CLOSE_STYLE_SKIP}`:\n"
                      f"   {url}")

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

    def search_bing(
            self, query: str, n: int, types = ["News"],
            return_content = True, promote=["News"]
        ):

        global _bing_subscription_key

        assert _bing_subscription_key

        search_url = "https://api.bing.microsoft.com/v7.0/search"
        print(f"n={n} responseFilter={types}")
        headers = {"Ocp-Apim-Subscription-Key": _bing_subscription_key}
        params = {"q": query, "textDecorations":True,
            "textFormat": "HTML", "responseFilter":types, 
            "promote":promote, "answerCount":5}
        response = requests.get(search_url, headers=headers, params=params)
        response.raise_for_status()
        search_results = response.json()

        items = []
        if "news" in search_results and "value" in search_results["news"]:
            print(f'bing adding {len(search_results["news"]["value"])} news')
            items = items + search_results["news"]["value"]

        if "webPages" in search_results and "value" in search_results["webPages"]:
            print(f'bing adding {len(search_results["webPages"]["value"])} webPages')
            items = items + search_results["webPages"]["value"]

        if "entities" in search_results and "value" in search_results["entities"]:
            print(f'bing adding {len(search_results["entities"]["value"])} entities')
            items = items + search_results["entities"]["value"]

        if "places" in search_results and "value" in search_results["places"]:
            print(f'bing adding {len(search_results["places"]["value"])} places')
            items = items + search_results["places"]["value"]

        urls = []
        contents = []
        news_count = 0

        for item in items:
            if "url" not in item:
                continue
            else:
                url = item["url"]

            title = item["name"]

            # Remove Bing formatting characters from title
            title = filter_html(title)

            if title is None or title == "":
                print("No title to skipping")
                continue

            if return_content:
                content = title + ". "
                if "snippet" in item :
                    snippet = filter_html(item["snippet"])
                    content += snippet
                    print(f"Adding webpage summary with title {title} for url {url}")
                    contents.append({'title': title, 'url': url, 'content': content})

                elif "description" in item:
                    if news_count < 3:
                        text = filter_html(item["description"])
                        content += text
                        news_count += 1
                        contents.append({'title': title, 'url': url, 'content': content})
                else:
                    print(f"Could not find descripton for item {item}")
            else:
                urls.append(url)

        if len(urls) == 0 and not return_content:
           print(f"Warning: No Bing URLs found for query {query}")

        if return_content:
            return contents
        else:
            return urls

def filter_html(title):
    title.replace("<b>", "")
    title = title.replace("<b>", "")
    title = title.replace("</b>", "")
    title = title.replace("</br>", "")
    title = title.replace("\u2018", "")
    title = title.replace("\u2018", "")
    title = title.replace("\u00b7", "")
    title = title.replace("&amp", "")
    title = title.replace("</br>", "")
    title = title.replace("&#39", "")
    return title

class GoogleSearchServer(SearchABC):
    def search(self, q: str, n: int) -> Generator[str, None, None]:
        return googlesearch.search(q, num=n, stop=None, pause=_DELAY_SEARCH)

class Application:
    def serve(
        self, host: str = _DEFAULT_HOST,
        requests_get_timeout = _requests_get_timeout,
        strip_html_menus = _strip_html_menus,
        max_text_bytes = _max_text_bytes,
        use_bing = _use_bing,
        use_bing_description_only = _use_bing_description_only,
        bing_subscription_key = None) -> NoReturn:

        global _requests_get_timeout, _strip_html_menus, _max_text_bytes
        global _use_bing, _use_bing_description_only, _bing_subscription_key

        """ Main entry point: Start the server.
        Arguments:
            host (str):
            requests_get_timeout (int):
            strip_html_menus (bool):
            max_text_bytes (int):
            use_bing (bool):
            use_bing_description_only (bool):
            bing_subscription_key (str):
        HOSTNAME:PORT of the server. HOSTNAME can be an IP.
        Most of the time should be 0.0.0.0. Port 8080 doesn't work on colab.
        Other ports also probably don't work on colab, test it out.
        requests_get_timeout is seconds before each url fetch times out
        strip_html_menus removes likely menus to clean up text
        max_text_bytes limits the bytes returned per web page. Note,
            ParlAI current defaults to 512 bytes
        use_bing set to True will use Bing instead of Google
        use_bing_description_only are short but 10X faster since no url gets
        bing_subscription_key required to use bing. Can get one at:
            https://www.microsoft.com/en-us/bing/apis/bing-entity-search-api
        """

        hostname, port = _parse_host(host)
        host = f"{hostname}:{port}"

        _requests_get_timeout = requests_get_timeout
        _strip_html_menus = strip_html_menus
        _max_text_bytes = max_text_bytes
        _use_bing = use_bing
        _use_bing_description_only = use_bing_description_only
        _bing_subscription_key = bing_subscription_key

        self.check_and_print_cmdline_args()

        with http.server.ThreadingHTTPServer(
            (hostname, int(port)), GoogleSearchServer
        ) as server:
            print("Serving forever.")
            print(f"Host: {host}")
            server.serve_forever()

    def check_and_print_cmdline_args(
        self) -> None:
        if _use_bing and _bing_subscription_key is None:
            print("--bing_subscription_key required to use bing search")
            print("To get one go to url:")
            print("https://www.microsoft.com/en-us/bing/apis/bing-entity-search-api")
            exit()

        print("Command line args used:")
        print(f"  requests_get_timeout={_requests_get_timeout}")
        print(f"  strip_html_menus={_strip_html_menus}")
        print(f"  max_text_bytes={_max_text_bytes}")
        print(f"  use_bing={_use_bing}")
        print(f"  use_bing_description_only={_use_bing_description_only}")

    def test_parser(self, url: str) -> None:
        """ Test the webpage getter and parser.
        Will try to download the page, then parse it, then will display the result.
        """
        print(_get_and_parse(url))

    def test_server(
            self, query: str, n: int, host : str = _DEFAULT_HOST,
            requests_get_timeout = _requests_get_timeout,
            strip_html_menus = _strip_html_menus,
            max_text_bytes = _max_text_bytes,
            use_bing = _use_bing,
            use_bing_description_only = _use_bing_description_only,
            bing_subscription_key = None
        ) -> None:

        global _requests_get_timeout, _strip_html_menus, _max_text_bytes
        global _use_bing, _use_bing_description_only, _bing_subscription_key

        """ Creates a thin fake client to test a server that is already up.
        Expects a server to have already been started with `python search_server.py serve [options]`.
        Creates a retriever client the same way ParlAi client does it for its chat bot, then
        sends a query to the server.
        """
        host, port = _parse_host(host)

        _requests_get_timeout = requests_get_timeout
        _strip_html_menus = strip_html_menus
        _max_text_bytes = max_text_bytes
        _use_bing = use_bing
        _use_bing_description_only = use_bing_description_only

        print(f"Query: `{query}`")
        print(f"n: {n}")

        self.check_and_print_cmdline_args()

        retriever = parlai.agents.rag.retrieve_api.SearchEngineRetriever(
            dict(
                search_server=f"{host}:{port}",
                skip_retrieval_token=False,
            )
        )
        print("Retrieving one.")
        print(retriever.retrieve([query], n))
        print("Done.")


if __name__ == "__main__":
    fire.Fire(Application)
