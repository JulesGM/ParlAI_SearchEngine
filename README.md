# Description
A web search server for ParlAI, including Blenderbot2.


*Querying the server:*<br>
<img src="imgs/blenderbot2_demo.png" width="70%" 
alt="Shows a small dialog, with the human asking who Alexander the Great is, and the bot answering that he is a Macedonian king">

*The server reacting correctly:*<br>
<img src="imgs/server_demo.png" width="70%" 
alt="Shows lines with search results, the titles and the urls.">


- Uses `html2text` to strip the markup out of the page.
- Uses `beautifulsoup4` to parse the title.
- Supports both Google (default) and Bing search, but is coded in a modular / search engine agnostic 
way to allow very easily add new search engine support. Bing search requires a API subscription key, 
which can be obtained for free at: https://www.microsoft.com/en-us/bing/apis/bing-entity-search-api


Using the `googlesearch` module is very slow because it parses Google search webpages instead of querying cloud webservices. This is fine for playing with the model, but makes that searcher unusable for training or large scale inference purposes. In the paper, Bing cloud services are used, matching the results over Common Crawl instead of just downloading the page.

# Quick Start:

First install the requirements:
```bash
pip install -r requirements.txt
```

Run this command in one terminal tab:
```bash
python search_server.py serve --host 0.0.0.0:8080
```

[Optional] You can then test the server with 
```
curl -X POST "http://0.0.0.0:8080" -d "q=baseball&n=1"
```

Then for example start Blenderbot2 in a different terminal tab:
```
python -m parlai interactive --model-file zoo:blenderbot2/blenderbot2_3B/model --search_server 0.0.0.0:8080
```

# Colab
There is a jupyter notebook. Just run it. Some instances run out of memory, some don't.

# Other Ways to Test the Server:

This method creates a retrieval client class instance the same way the ParlAI code would, and tries to retrieve from the server. If you have a server running, you can use this to test the server without having to load the (very large) dialog model. This will create a `parlai.agents.rag.retrieve_api.SearchEngineRetriever` and try to connect and send a query, and parse the answer.

```bash
python search_server.py serve --host 0.0.0.0:8080
```
then in a different tab

```bash
python search_server.py test_server --host 0.0.0.0:8080
```

# Testing the parser:

```bash
python search_server.py test_parser www.some_url_of_your_choice.com/
```

# Additional Command Line Parameters

- requests_get_timeout - sets the timeout for URL requests to fetch content of URLs found during search. Defaults to 5 seconds.
- strip_html_menus - removes likely HTML menus to clean up text. This returns significantly higher quality and informationally dense text. 
- max_text_bytes limits the bytes returned per web page. Defaults to no max.  Note, ParlAI current defaults to only use the first 512 byte. 
- search_engine set to "Google" default or "Bing". Note, the Bing Search engine was used in the Blenderbot2 paper to achieve their results.  This implementation not only uses web pages but also news, entities and places.
- use_description_only are short but 10X faster since no url gets for Bing only. It also has the advantage of being very concise without an HTML irrelevant text normally returned.
- use_subscription_key required to use Bing only. Can get a free one at: https://www.microsoft.com/en-us/bing/apis/bing-entity-search-api

# Advanced Examples

Google Search Engine returning more relevant information than the defaults:
```bash
python search_server.py serve --host 0.0.0.0:8080 --max_text_bytes 512 --requests_get_timeout 10 --strip_html_menus
```

Bing Search Engine:
```bash
python search_server.py serve --host 0.0.0.0:8080 --search_engine="Bing" --subscription_key "put your bing api subscription key here"
```

Bing Search Engine returning more relevant information:
```bash
python search_server.py serve --host 0.0.0.0:8080 --search_engine="Bing" --max_text_bytes=512 --requests_get_timeout 10 --strip_html_menus --subscription_key "put your bing api subscription key here"
```

Bing Search Engine returning very relevant concise information 10X faster. Returns a 250 to 350 byte web page summary per URL including the web page title:
```bash
python search_server.py serve --host 0.0.0.0:8080 --search_engine="Bing" --use_description_only --subscription_key "put your bing api subscription key here"
```

# Additional Command Line Example Test Calls

```bash
curl -X POST "http://0.0.0:8080" -d "q=Which%20team%20does%20Tom%20Brady%20play%20for%20now&n=6"
```

```bash
curl -X POST "http://0.0.0:8080" -d "q=Where%20Are%20The%20Olympics%20Being%20Held%20in%202021&n=6"
```
