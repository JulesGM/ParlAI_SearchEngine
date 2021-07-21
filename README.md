A web search server for ParlAI, including Blenderbot2.


*Querying the server:*
![Querying the server](imgs/blenderbot2_demo.png)

*The server reacting correctly:*
![The server reacting appropriately](imgs/server_demo.png)


- Uses `html2text` to strip the markup out of the page.
- Uses `beautifulsoup4` to parse the title.
- Currently only uses the `googlesearch` module to query Google for urls, but is coded
in a modular / search engine agnostic way to allow very easily add new search engine support.


Using the `googlesearch` module is very slow because it parses webpages instead of querying webservices. This is fine for playing with the model, but makes that searcher unusable for training or large scale inference purposes.


To be able to train, one would just have to for example pay for Google Cloud or Microsoft Azure's search services, and derive the Search class to query them.

### Quick Start:
Run this command in one terminal tab:
```bash
python search_server.py serve --host 0.0.0.0:8080
```

and then for example start Blenderbot2 in a different terminal tab:
```
python -m parlai interactive --model-file zoo:blenderbot2/blenderbot2_3B/model --search_server 0.0.0.0:8080
```

### Colab:

To run in colab, start the server first in a cell with the following code:

```
import multiprocess
import subprocess
PATH_TO_SEARCH_SERVER = "./search_server.py --host 0.0.0.0:8080"
def start_server():
    subprocess.check_call(f"python {PATH_TO_SEARCH_SERVER} serve" , shell=True)
multiprocess.Process(target=start_server).start()
```

Change `PATH_TO_SEARCH_SERVER` as needed to point to the script.

Then start Blenderbot 2.0 as you normally would, by running the following in a cell:

```
!python -m parlai interactive --model-file zoo:blenderbot2/blenderbot2_3B/model --search_server 0.0.0.0:8080
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
