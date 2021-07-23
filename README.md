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
- Currently only uses the `googlesearch` module to query Google for urls, but is coded
in a modular / search engine agnostic way to allow very easily add new search engine support.


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
