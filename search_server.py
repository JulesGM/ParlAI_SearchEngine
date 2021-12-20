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

import os
import random

# get preset configs
search_engine_ev = "google"
search_api_key_ev = None

# default url
aquila_url_ev = "https://x.aquila.network/api/search"

server_host_ev = "0.0.0.0"
server_port_ev = 8080

if os.getenv('SEARCH_ENGINE'):
    search_engine_ev = os.getenv('SEARCH_ENGINE')
    
if search_engine_ev == "aquila":
    search_api_key_ev = os.getenv('SEARCH_API_KEY')
    if os.getenv('AQUILA_URL'):
        aquila_url_ev = os.getenv('AQUILA_URL')

if os.getenv('HOST'):
    server_host_ev = os.getenv('HOST')

if os.getenv('PORT'):
    server_port_ev = os.getenv('PORT')


print = rich.print

_DEFAULT_HOST = server_host_ev
_DEFAULT_PORT = server_port_ev
_DELAY_SEARCH = 1.0  # Making this too low will get you IP banned
_STYLE_GOOD = "[green]"
_STYLE_SKIP = ""
_CLOSE_STYLE_GOOD = "[/]" if _STYLE_GOOD else ""
_CLOSE_STYLE_SKIP = "[/]" if _STYLE_SKIP else ""
_REQUESTS_GET_TIMEOUT = 5


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


class SearchABC(http.server.BaseHTTPRequestHandler):
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
        
        # Search until we have n valid entries
        for url in self.search(q=q, n=n):
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
        # pick_list = [
        #     "Elon Reeve Musk FRS (born June 28, 1971) is an entrepreneur and business magnate. He is the founder, CEO and Chief Engineer at SpaceX; early-stage investor, CEO and Product Architect of Tesla, Inc.; founder of The Boring Company; and co-founder of Neuralink and OpenAI. With an estimated net worth of around US$270 billion as of December 2021,[2] Musk is the richest person in the world.",
        #     "Musk was born to a Canadian mother and South African father, and raised in Pretoria, South Africa. He briefly attended the University of Pretoria before moving to Canada at age 17 to avoid conscription. He was enrolled at Queen's University and later transferred to the University of Pennsylvania two years later, where he received a bachelor's degree in economics and physics, then moved to California in 1995 to attend Stanford University but decided instead to pursue a business career, co-founding the web software company Zip2 with his brother Kimbal. The startup was acquired by Compaq for $307 million in 1999. The same year, Musk co-founded online bank X.com, which merged with Confinity in 2000 to form PayPal. The company was bought by eBay in 2002 for $1.5 billion.",
        #     "In 2002, Musk founded SpaceX, an aerospace manufacturer and space transport services company, of which he is CEO and CTO. In 2004, he joined electric vehicle manufacturer Tesla Motors, Inc. (now Tesla, Inc.) as chairman and product architect, becoming its CEO in 2008. In 2006, he helped create SolarCity, a solar energy services company that was later acquired by Tesla and became Tesla Energy. In 2015, he co-founded OpenAI, a nonprofit research company that promotes friendly artificial intelligence. In 2016, he co-founded Neuralink, a neurotechnology company focused on developing brain computer interfaces, and founded The Boring Company, a tunnel construction company. Musk has proposed the Hyperloop, a high-speed vactrain transportation system.",
        #     "Musk has been the subject of criticism due to unorthodox or unscientific stances and highly publicized controversies. In 2018, he was sued for defamation by a British caver who advised in the Tham Luang cave rescue; a California jury ruled in favor of Musk. In the same year, he was sued by the US Securities and Exchange Commission (SEC) for falsely tweeting that he had secured funding for a private takeover of Tesla. He settled with the SEC, temporarily stepping down from his chairmanship and agreed to limitations on his Twitter usage. Musk has spread misinformation about the COVID-19 pandemic and has received criticism from experts for his other views on such matters as artificial intelligence, cryptocurrency, and public transport. "
        # ]
        # content = []
        
        # for itm in pick_list:
        #     content.append({
        #         'title': 'elon musk', 
        #         'content': itm, 
        #         'url': 'https://apple.com'
        #     })
        # print(random.choice(content)["content"])
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
        return googlesearch.search(q, num=n, stop=None, pause=_DELAY_SEARCH)

class FAISSSearchServer(SearchABC):
    def search(self, q: str, n: int) -> Generator[str, None, None]:
        payload = json.dumps({
            "publicIndexId": search_api_key_ev,
            "query": q
        })
        headers = {
            'Content-Type': 'application/json'
        }

        response = requests.request("POST", aquila_url_ev, headers=headers, data=payload)
        resp_ = dict(sorted(response.json()['result'].items(), key=lambda item: item[1], reverse=True))
        ret_ = list(resp_.keys())[:n]

        return ret_


class Application:
    def serve(
        self, host: str = _DEFAULT_HOST) -> NoReturn:
        """ Main entry point: Start the server.
        Arguments:
            host (str):
        HOSTNAME:PORT of the server. HOSTNAME can be an IP. 
        Most of the time should be 0.0.0.0. Port 8080 doesn't work on colab.
        Other ports also probably don't work on colab, test it out.

        """

        hostname, port = _parse_host(host)
        host = f"{hostname}:{port}"

        if search_engine_ev == "google":
            print("Starting Google Search server..")
            with http.server.ThreadingHTTPServer(
                (hostname, int(port)), GoogleSearchServer
            ) as server:
                print("Serving forever.")
                print(f"Host: {host}")
                server.serve_forever()
        elif search_engine_ev == "aquila":
            print("Starting Aquila Search server..")
            with http.server.ThreadingHTTPServer(
                (hostname, int(port)), FAISSSearchServer
            ) as server:
                print("Serving forever.")
                print(f"Host: {host}")
                server.serve_forever()
        else:
            print("Choose a search server.")

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
