A web search server for ParlAI, including Blenderbot2.

### Quick Start:

```bash
python search_server.py serve --host=0.0.0.0:8080
```

You can then for example start Blenderbot2 passing the server's address and ip as arguments:
```
parlai --model-file zoo:blenderbot2/blenderbot2_3B/model --search_server=0.0.0.0:8080
```

### Testing the server:
You need to already be running a server by calling serve on the same hostname and ip. 
This will create a parlai.agents.rag.retrieve_api.SearchEngineRetriever and try to connect 
and send a query, and parse the answer.

```bash
python search_server.py test_server --host=0.0.0.0:8080
```

### Testing the parser:

```bash
python search_server.py test_parser www.some_url_of_your_choice.com/
```
