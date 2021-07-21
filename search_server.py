"""
A web search server for ParlAI, including Blenderbot2.

- Uses `html2text` to strip the markup out of the page.
- Uses `beautifulsoup4` to parse the title.
- Currently only uses the `googlesearch` module to query Google for urls, but is coded
in a modular / search engine agnostic way to allow very easily add new search engine support.

Using the `googlesearch` module is very slow because it parses webpages instead of querying webservices. This is fine for playing with the model, but makes that searcher unusable for training or large scale inference purposes.

To be able to train, one would just have to for example pay for Google Cloud or Microsoft Azure's search services, and derive the Search class to query them.

### Quick Start:

```bash
python search_server.py serve --host 0.0.0.0:8080
```

You can then for example start Blenderbot2 passing the server's address and ip as arguments:
```
parlai --model-file zoo:blenderbot2/blenderbot2_3B/model --search_server 0.0.0.0:8080
```


### Testing the server:
You need to already be running a server by calling serve on the same hostname and ip. 
This will create a parlai.agents.rag.retrieve_api.SearchEngineRetriever and try to connect 
and send a query, and parse the answer.

```bash
python search_server.py test_server --host 0.0.0.0:8080
```

### Testing the parser:

```bash
python search_server.py test_parser www.some_url_of_your_choice.com/
```


"""
import http.server
import json
from typing import *
import urllib.parse

import bs4
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

def _parse_host(host: str) -> Tuple[str, str]:
    splitted = host.split(":")
    hostname = splitted[0]
    port = splitted[1] if len(splitted) > 1 else _DEFAULT_PORT
    return hostname, port


def _get_content(url: str) -> Dict[str, str]:
    resp = requests.get(url)
    try:
        resp = requests.get(url)
        page = resp.content
    except Exception as e:
        print(e)
        return {"content": ""}


    soup = bs4.BeautifulSoup(page, features="lxml")
    pre_rendered = soup.find("title")
    title = (
        pre_rendered.renderContents().decode() if pre_rendered else None
    )

    text_maker = html2text.HTML2Text()
    text_maker.ignore_links = True
    text_maker.ignore_tables = True
    text_maker.ignore_images = True
    text_maker.ignore_emphasis = True
    text_maker.single_line = True
    text = text_maker.handle(page.decode("utf-8", errors="ignore"))
    output_dict = dict(url=url, content=text)
    if title:
        output_dict["title"] = title
    print(
        f"title: `{rich.markup.escape(output_dict['title'])}`",
        f"url: {rich.markup.escape(output_dict['url'])}",
    )
    return output_dict


class SearchABC(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)

        # query = urllib.parse.urlparse(post_data).query
        parsed = urllib.parse.parse_qs(post_data)
        for k, v in parsed.items():
            assert len(v) == 1, len(v)

        parsed = {k.decode(): v[0].decode() for k, v in parsed.items()}

        print(f"parsed: {parsed}")
        n = int(parsed["n"])
        q = parsed["q"]

        urls = self.search(q=q, n=n)

        output = json.dumps(
            dict(response=[_get_content(url) for url in urls])
        ).encode()
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", len(output))
        self.end_headers()
        self.wfile.write(output)

    def search(self, q: str, n: int):
        return NotImplemented(
            "Search is an abstract base class, not meant to be directly instantiated. "
            "You should instantiate a derived class like GoogleSearch."
        )
    

class GoogleSearchServer(SearchABC):
    def search(self, q: str, n: int):
        return googlesearch.search(q, num=n, stop=n)
    

class Application:
    def serve(self, host: str = _DEFAULT_HOST) -> NoReturn:
        host, port = _parse_host(host)

        with http.server.ThreadingHTTPServer((host, port), GoogleSearchServer) as server:
            print("Serving forever.")
            server.serve_forever()

    def test_parser(self, url):
        print(_get_content(url))

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
