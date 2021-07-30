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
_REQUESTS_GET_TIMEOUT = 5 # seconds

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

    try:
        resp = requests.get(url, timeout=_REQUESTS_GET_TIMEOUT)
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

class SearchABCRequestHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):

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
        print(f"\n[bold]Received query:[/] {parsed}")

        n = int(parsed["n"])
        q = parsed["q"]

        # Over query a little bit in case we find useless URLs
        content = []
        dupe_detection_set = set()

        urls = []
        results = self.search(q=q, n=n, 
            subscription_key = self.server.subscription_key, 
            use_description_only=self.server.use_description_only)

        if self.server.use_description_only:
            content = results
        else:
            urls = results

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
                reason_content_forbidden = (
                    maybe_content["content"] == "Forbidden"
                )
            else:
                reason_content_empty = False
                reason_already_seen_content = False
                reason_content_forbidden = False
 
            reasons = dict(
                reason_empty_response=reason_empty_response,
                reason_content_empty=reason_content_empty,
                reason_already_seen_content=reason_already_seen_content,
                reason_content_forbidden=reason_content_forbidden,
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
                if self.server.strip_html_menus:
                    new_content = ""
                    for line in maybe_content['content'].splitlines():
                        x = re.findall("^[\s]*\\* ", line)
                        if line != "" and (not x or len(line) > 50):
                            new_content += line + "\n"

                    maybe_content['content'] = filter_special_chars(new_content)

                # Truncate text
                maybe_content['content'] = maybe_content['content'][:self.server.max_text_bytes]

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

    def search(self, 
            q: str, n: int, 
            subscription_key: str = "", 
            use_description_only: bool = False
        ) -> Generator[str, None, None]:

        return NotImplemented(
            "Search is an abstract base class, not meant to be directly "
            "instantiated. You should instantiate a derived class like "
            "GoogleSearch."
        )

def filter_special_chars(title):
    title = title.replace("&quot", "")
    title = title.replace("&amp", "")
    title = title.replace("&gt", "")
    title = title.replace("&lt", "")
    title = title.replace("&#39", "")
    title = title.replace("\u2018", "") # unicode single quote
    title = title.replace("\u2019", "") # unicode single quote
    title = title.replace("\u201c", "") # unicode left double quote 
    title = title.replace("\u201d", "") # unicode right double quote 
    title = title.replace("\u8220", "") # unicode left double quote 
    title = title.replace("\u8221", "") # unicode right double quote
    title = title.replace("\u8222", "") # unicode double low-9 quotation mark
    title = title.replace("\u2022", "") # unicode bullet 
    title = title.replace("\u2013", "") # unicode dash 
    title = title.replace("\u00b7", "") # unicode middle dot
    title = title.replace("\u00d7", "") # multiplication sign
    return title

class BingSearchRequestHandler(SearchABCRequestHandler):
    bing_search_url = "https://api.bing.microsoft.com/v7.0/search"

    def search(self, 
            q: str, n: int, 
            subscription_key: str = None, 
            use_description_only: bool = False
        ) -> Generator[str, None, None]:

        assert subscription_key
        types = ["News", "Entities", "Places", "Webpages"]
        promote = ["News"]

        print(f"n={n} responseFilter={types}")
        headers = {"Ocp-Apim-Subscription-Key": subscription_key}
        params = {"q": q, "textDecorations":False,
            "textFormat": "HTML", "responseFilter":types, 
            "promote":promote, "answerCount":5}
        response = requests.get(BingSearchRequestHandler.bing_search_url, 
            headers=headers, params=params)
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
            title = filter_special_chars(title)

            if title is None or title == "":
                print("No title to skipping")
                continue

            if self.server.use_description_only:
                content = title + ". "
                if "snippet" in item :
                    snippet = filter_special_chars(item["snippet"])
                    content += snippet
                    print(f"Adding webpage summary with title {title} for url {url}")
                    contents.append({'title': title, 'url': url, 'content': content})

                elif "description" in item:
                    if news_count < 3:
                        text = filter_special_chars(item["description"])
                        content += text
                        news_count += 1
                        contents.append({'title': title, 'url': url, 'content': content})
                else:
                    print(f"Could not find descripton for item {item}")
            else:
                if url not in urls:
                    urls.append(url)

        if len(urls) == 0 and not use_description_only:
           print(f"Warning: No Bing URLs found for query {q}")

        if use_description_only:
            return contents
        else:
            return urls

class GoogleSearchRequestHandler(SearchABCRequestHandler):
    def search(self, q: str, n: int,
            subscription_key: str = None,
            use_description_only: bool = False
        ) -> Generator[str, None, None]:

        return googlesearch.search(q, num=n, stop=None, pause=_DELAY_SEARCH)

class SearchABCServer(http.server.ThreadingHTTPServer):
    def __init__(self, 
            server_address, RequestHandlerClass, 
            max_text_bytes, strip_html_menus,
            use_description_only = False, subscription_key = None 
        ):

        self.max_text_bytes = max_text_bytes
        self.strip_html_menus = strip_html_menus
        self.use_description_only = use_description_only
        self.subscription_key = subscription_key

        super().__init__(server_address, RequestHandlerClass)

class Application:
    def serve(
            self, host: str = _DEFAULT_HOST,
            requests_get_timeout = _REQUESTS_GET_TIMEOUT,
            strip_html_menus = False,
            max_text_bytes = None,
            search_engine = "Google",
            use_description_only = False,
            subscription_key = None
        ) -> NoReturn:
        """ Main entry point: Start the server.
        Arguments:
            host (str):
            requests_get_timeout (int):
            strip_html_menus (bool):
            max_text_bytes (int):
            search_engine (str):
            use_description_only (bool):
            subscription_key (str):
        HOSTNAME:PORT of the server. HOSTNAME can be an IP.
        Most of the time should be 0.0.0.0. Port 8080 doesn't work on colab.
        Other ports also probably don't work on colab, test it out.
        requests_get_timeout defaults to 5 seconds before each url fetch times out.
        strip_html_menus removes likely HTML menus to clean up text.
        max_text_bytes limits the bytes returned per web page. Set to no max.
            Note, ParlAI current defaults to 512 byte.
        search_engine set to "Google" default or "Bing"
        use_description_only are short but 10X faster since no url gets 
            for Bing only
        use_subscription_key required to use Bing only. Can get a free one at:
            https://www.microsoft.com/en-us/bing/apis/bing-entity-search-api

        """

        global _REQUESTS_GET_TIMEOUT

        hostname, port = _parse_host(host)
        host = f"{hostname}:{port}"

        _REQUESTS_GET_TIMEOUT = requests_get_timeout

        self.check_and_print_cmdline_args(max_text_bytes, strip_html_menus,
            search_engine, use_description_only, subscription_key)

        if search_engine == "Bing":
            request_handler = BingSearchRequestHandler
        else:
            request_handler = GoogleSearchRequestHandler

        with SearchABCServer(
                (hostname, int(port)), request_handler, 
                max_text_bytes, strip_html_menus, 
                use_description_only, subscription_key
            ) as server:
                print("Serving forever.")
                print(f"Host: {host}")
                server.serve_forever()

    def check_and_print_cmdline_args(
            self, max_text_bytes, strip_html_menus,
            search_engine, use_description_only, subscription_key
        ) -> None:

        if search_engine == "Bing":
            if subscription_key is None:
                print("Warning: subscription_key is required for Bing Search Engine")
                print("To get one go to url:")
                print("https://www.microsoft.com/en-us/bing/apis/bing-entity-search-api")
                exit()
        elif search_engine == "Google":
            if use_description_only:
                print("Warning: use_description_only is not supported for Google Search Engine")
                exit()
            if subscription_key is not None:
                print("Warning: subscription_key is not supported for Google Search Engine")
                exit()

        print("Command line args used:")
        print(f"  requests_get_timeout={_REQUESTS_GET_TIMEOUT}")
        print(f"  strip_html_menus={strip_html_menus}")
        print(f"  max_text_bytes={max_text_bytes}")
        print(f"  search_engine={search_engine}")
        print(f"  use_description_only={use_description_only}")

    def test_parser(self, url: str) -> None:
        """ Test the webpage getter and parser.
        Will try to download the page, then parse it, then will display the result.
        """
        print(_get_and_parse(url))

    def test_server(self, query: str, n: int, host : str = _DEFAULT_HOST) -> None:

        """ Creates a thin fake client to test a server that is already up.
        Expects a server to have already been started with `python search_server.py serve [options]`.
        Creates a retriever client the same way ParlAi client does it for its chat bot, then
        sends a query to the server.
        """
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
        print(retriever.retrieve([query], n))
        print("Done.")


if __name__ == "__main__":
    fire.Fire(Application)
