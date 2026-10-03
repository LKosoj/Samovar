#include "asyncHTTPrequest.h"
#include <new>

//**************************************************************************************************************
asyncHTTPrequest::asyncHTTPrequest()
    : _readyState(readyStateUnsent)
    , _HTTPcode(0)
    , _chunked(false)
    , _debug(DEBUG_IOTA_HTTP_SET)
    , _timeout(DEFAULT_RX_TIMEOUT)
    , _lastActivity(0)
    , _requestStartTime(0)
    , _requestEndTime(0)
    , _URL(nullptr)
    , _connectedHost(nullptr)
    , _connectedPort(-1)
    , _client(nullptr)
    , _contentLength(0)
    , _contentRead(0)
    , _readyStateChangeCB(nullptr)
    , _readyStateChangeCBarg(nullptr)
    , _onDataCB(nullptr)
    , _onDataCBarg(nullptr)
    , _request(nullptr)
    , _response(nullptr)
    , _chunks(nullptr)
    , _headers(nullptr)
{
    DEBUG_HTTP("New request.");
#ifdef ESP32
    threadLock = xSemaphoreCreateRecursiveMutex();
#endif
}

//**************************************************************************************************************
asyncHTTPrequest::~asyncHTTPrequest(){
    // ЗАЩИТА: проверяем перед удалением
    if(_client) {
    _client->close();
        delete _client;
        _client = nullptr;
    }
    delete _URL;
    delete _headers;
    delete _request;
    delete _response;
    delete _chunks;
#ifdef ESP32
    vSemaphoreDelete(threadLock);
#endif
}

//**************************************************************************************************************
void    asyncHTTPrequest::setDebug(bool debug){
    if(_debug || debug) {
        _debug = true;
        DEBUG_HTTP("setDebug(%s) version %s\r\n", debug ? "on" : "off", asyncHTTPrequest_h);
    }
	_debug = debug;
}

//**************************************************************************************************************
bool    asyncHTTPrequest::debug(){
    return(_debug);
}

//**************************************************************************************************************
bool	asyncHTTPrequest::open(const char* method, const char* URL){
    DEBUG_HTTP("open(%s, %.32s)\r\n", method, URL);
    if(_readyState != readyStateUnsent && _readyState != readyStateDone) {return false;}
    _requestStartTime = millis();
    delete _URL;
    delete _headers;
    delete _request;
    delete _response;
    delete _chunks;
    _URL = nullptr;
    _headers = nullptr;
    _response = nullptr;
    _request = nullptr;
    _chunks = nullptr;
    _chunked = false;
    _contentRead = 0;
    _HTTPcode = 0;
    _readyState = readyStateUnsent;

    if (strcmp(method, "GET") == 0) {
        _HTTPmethod = HTTPmethodGET;
    } else if (strcmp(method, "POST") == 0) {
        _HTTPmethod = HTTPmethodPOST;
    } else
        return false;

    if (!_parseURL(URL)) {
        return false;}
    if( _client && _client->connected() && 
      (strcmp(_URL->host, _connectedHost) != 0 || _URL->port != _connectedPort)){return false;}
    char* hostName = new (std::nothrow) char[strlen(_URL->host)+10];
    if(!hostName){ _failRequest(HTTPCODE_TOO_LESS_RAM); return false; }
    sprintf(hostName,"%s:%d", _URL->host, _URL->port);  
    const bool hostAdded = _addHeader("host",hostName) != nullptr;
    delete[] hostName;
    if(!hostAdded) return false;
    _lastActivity = millis();
	return _connect();
}
//**************************************************************************************************************
void    asyncHTTPrequest::onReadyStateChange(readyStateChangeCB cb, void* arg){
    _readyStateChangeCB = cb;
    _readyStateChangeCBarg = arg;
}

void asyncHTTPrequest::setMaxResponseBufferSize(uint16_t bytes){
    _seize;
    _maxResponseBufferBytes = bytes;
    _release;
}

//**************************************************************************************************************
void	asyncHTTPrequest::setTimeout(int seconds){
    DEBUG_HTTP("setTimeout(%d)\r\n", seconds);
    _timeout = seconds;
}

//**************************************************************************************************************
bool	asyncHTTPrequest::send(){
    DEBUG_HTTP("send()\r\n");
    _seize;
    if( ! _buildRequest()){
        _release;
        return false;
    }
    _send();
    _release;
    return true;
}

//**************************************************************************************************************
bool    asyncHTTPrequest::send(String body){
    DEBUG_HTTP("send(String) %s... (%d)\r\n", body.substring(0,16).c_str(), body.length());
    _seize;
    _addHeader("Content-Length", String(body.length()).c_str());
    if( ! _buildRequest()){
        _release;
        return false;
    }
    if(_request->write(body) != body.length()){
        _failRequest(HTTPCODE_TOO_LESS_RAM);
        _release;
        return false;
    }
    _send();
    _release;
    return true;
}

//**************************************************************************************************************
bool	asyncHTTPrequest::send(const char* body){
    DEBUG_HTTP("send(char*) %s.16... (%d)\r\n",body, strlen(body));
    _seize;
    _addHeader("Content-Length", String(strlen(body)).c_str());
    if( ! _buildRequest()){
        _release;
        return false;
    } 
    if(_request->write(body) != strlen(body)){
        _failRequest(HTTPCODE_TOO_LESS_RAM);
        _release;
        return false;
    }
    _send();
    _release;
    return true;
}

//**************************************************************************************************************
bool	asyncHTTPrequest::send(const uint8_t* body, size_t len){
    DEBUG_HTTP("send(char*) %s.16... (%d)\r\n",(char*)body, len);
    _seize;
    _addHeader("Content-Length", String(len).c_str());
    if( ! _buildRequest()){
        _release;
        return false;
    } 
    if(_request->write(body, len) != len){
        _failRequest(HTTPCODE_TOO_LESS_RAM);
        _release;
        return false;
    }
    _send();
    _release;
    return true;
}

//**************************************************************************************************************
bool	asyncHTTPrequest::send(xbuf* body, size_t len){
    DEBUG_HTTP("send(char*) %s.16... (%d)\r\n", body->peekString(16).c_str(), len);
    _seize;
    _addHeader("Content-Length", String(len).c_str());
    if( ! _buildRequest()){
        _release;
        return false;
    } 
    if(_request->write(body, len) != len){
        _failRequest(HTTPCODE_TOO_LESS_RAM);
        _release;
        return false;
    }
    _send();
    _release;
    return true;
}

//**************************************************************************************************************
void    asyncHTTPrequest::abort(){
    DEBUG_HTTP("abort()\r\n");
    _seize;
    // Выход без _release оставлял рекурсивный мьютекс захваченным: следующий вызов
    // любого метода объекта вставал на нём навсегда, а деструктор удалял занятый мьютекс.
    if(! _client){
        _release;
        return;
    }
    _client->abort();
    _release;
}
//**************************************************************************************************************
int		asyncHTTPrequest::readyState(){
    return _readyState;
}

//**************************************************************************************************************
int	asyncHTTPrequest::responseHTTPcode(){
    return _HTTPcode;
}

//**************************************************************************************************************
String	asyncHTTPrequest::responseText(){
    DEBUG_HTTP("responseText() ");
    _seize;
    if( ! _response || _readyState < readyStateLoading || ! available()){
        DEBUG_HTTP("responseText() no data\r\n");
        _release;
        return String(); 
    }       
    size_t avail = available();
    String localString = _response->readString(avail);
    if(localString.length() < avail) {
        DEBUG_HTTP("!responseText() no buffer\r\n")
        _HTTPcode = HTTPCODE_TOO_LESS_RAM;
        _client->abort();
        _release;
        return String();
    }
    _contentRead += localString.length();
    DEBUG_HTTP("responseText() %s... (%d)\r\n", localString.substring(0,16).c_str() , avail);
    _release;
    return localString;
}

//**************************************************************************************************************
size_t  asyncHTTPrequest::responseRead(uint8_t* buf, size_t len){
    if( ! _response || _readyState < readyStateLoading || ! available()){
        DEBUG_HTTP("responseRead() no data\r\n");
        return 0;
    } 
    _seize;
    size_t avail = available() > len ? len : available();
    _response->read(buf, avail);
    DEBUG_HTTP("responseRead() %.16s... (%d)\r\n", (char*)buf , avail);
    _contentRead += avail;
    _release;
    return avail;
}

//**************************************************************************************************************
size_t	asyncHTTPrequest::available(){
    if(_readyState < readyStateLoading || !_response) return 0;
    if(_chunked && (_contentLength - _contentRead) < _response->available()){
        return _contentLength - _contentRead;
    }
    return _response->available();
}

//**************************************************************************************************************
size_t	asyncHTTPrequest::responseLength(){
    if(_readyState < readyStateLoading) return 0;
    return _contentLength;
}

//**************************************************************************************************************
void	asyncHTTPrequest::onData(onDataCB cb, void* arg){
    DEBUG_HTTP("onData() CB set\r\n");
    _onDataCB = cb;
    _onDataCBarg = arg;
}

//**************************************************************************************************************
uint32_t asyncHTTPrequest::elapsedTime(){
    if(_readyState <= readyStateOpened) return 0;
    if(_readyState != readyStateDone){
        return millis() - _requestStartTime;
    }
    return _requestEndTime - _requestStartTime;
}

//**************************************************************************************************************
String asyncHTTPrequest::version(){
    return String(asyncHTTPrequest_h);
}

/*______________________________________________________________________________________________________________

               PPPP    RRRR     OOO    TTTTT   EEEEE    CCC    TTTTT   EEEEE   DDDD
               P   P   R   R   O   O     T     E       C   C     T     E       D   D
               PPPP    RRRR    O   O     T     EEE     C         T     EEE     D   D
               P       R  R    O   O     T     E       C   C     T     E       D   D
               P       R   R    OOO      T     EEEEE    CCC      T     EEEEE   DDDD
_______________________________________________________________________________________________________________*/

//**************************************************************************************************************
bool  asyncHTTPrequest::_parseURL(const char* url){
    delete _URL;
    _URL = new (std::nothrow) URL;
    if(!_URL){ _failRequest(HTTPCODE_TOO_LESS_RAM); return false; }
    _URL->buffer = new (std::nothrow) char[strlen(url) + 8];
    if(!_URL->buffer){ _failRequest(HTTPCODE_TOO_LESS_RAM); return false; }
    char *bufptr = _URL->buffer;
    const char *urlptr = url;

        // Find first delimiter

    int seglen = strcspn(urlptr, ":/?");

        // scheme

    _URL->scheme = bufptr;
    if(! memcmp(urlptr+seglen, "://", 3)){
        while(seglen--){
            *bufptr++ = toupper(*urlptr++);
        }
        urlptr += 3;
        seglen = strcspn(urlptr, ":/?");
    }
    else {
        memcpy(bufptr, "HTTP", 4);
        bufptr += 4;
    }
    *bufptr++ = 0;

        // host

    _URL->host = bufptr;
    memcpy(bufptr, urlptr, seglen);
    bufptr += seglen;
    *bufptr++ = 0;
    urlptr += seglen;

        // port 

    if(*urlptr == ':'){
        urlptr++;
        seglen = strcspn(urlptr, "/?");
        char *endptr = 0;
        _URL->port = strtol(urlptr, &endptr, 10);
        if((endptr-urlptr) != seglen){
            return false;
        }
        urlptr = endptr;
    }

        // path 

    _URL->path = bufptr;
    *bufptr++ = '/';
    if(*urlptr == '/'){
        seglen = strcspn(++urlptr, "?");
        memcpy(bufptr, urlptr, seglen);
        bufptr += seglen;
        urlptr += seglen;
    }
    *bufptr++ = 0;

        // query

    _URL->query = bufptr;
    if(*urlptr == '?'){
        seglen = strlen(urlptr);
        memcpy(bufptr, urlptr, seglen);
        bufptr += seglen;
        urlptr += seglen;
    }
    *bufptr++ = 0;

    if(strcmp(_URL->scheme, "HTTP")){
        return false;
    }

    DEBUG_HTTP("_parseURL() %s://%s:%d%s%.16s\r\n", _URL->scheme, _URL->host, _URL->port, _URL->path, _URL->query);
    return true;
}

//**************************************************************************************************************
bool  asyncHTTPrequest::_connect(){
    DEBUG_HTTP("_connect()\r\n");
	    // ++++ ДОБАВЬТЕ ЭТОТ БЛОК ++++
    DEBUG_HTTP("  > Creating new AsyncClient instance.\r\n");
    // +++++++++++++++++++++++++++++
    if( ! _client){
        _client = new (std::nothrow) AsyncClient();
        if(!_client){ _failRequest(HTTPCODE_TOO_LESS_RAM); return false; }
    }
	    // ++++ ДОБАВЬТЕ ЭТОТ БЛОК ++++
    DEBUG_HTTP("  > Attempting to connect to %s:%d\r\n", _URL->host, _URL->port);
    DEBUG_HTTP("  > Local port will be assigned by TCP stack.\r\n");
    // +++++++++++++++++++++++++++++
    delete[] _connectedHost;	
    _connectedHost = new (std::nothrow) char[strlen(_URL->host) + 1];
    if(!_connectedHost){ _failRequest(HTTPCODE_TOO_LESS_RAM); return false; }
    strcpy(_connectedHost, _URL->host);
    _connectedPort = _URL->port;
    _client->onConnect([](void *obj, AsyncClient *client){((asyncHTTPrequest*)(obj))->_onConnect(client);}, this);
    _client->onDisconnect([](void *obj, AsyncClient* client){((asyncHTTPrequest*)(obj))->_onDisconnect(client);}, this);
    _client->onPoll([](void *obj, AsyncClient *client){((asyncHTTPrequest*)(obj))->_onPoll(client);}, this);
    _client->onError([](void *obj, AsyncClient *client, uint32_t error){((asyncHTTPrequest*)(obj))->_onError(client, error);}, this);
    if( ! _client->connected()){
        if( ! _client->connect(_URL->host, _URL->port)) {
            DEBUG_HTTP("!client.connect(%s, %d) failed\r\n", _URL->host, _URL->port);
            _HTTPcode = HTTPCODE_NOT_CONNECTED;
            _setReadyState(readyStateDone);
            return false;
        }
    }
    else {
        _onConnect(_client);
    }
    _lastActivity = millis();
    return true;
}

//**************************************************************************************************************
bool   asyncHTTPrequest::_buildRequest(){
    DEBUG_HTTP("_buildRequest()\r\n");
    
        // Build the header.

    if(_HTTPcode < 0 || !_URL) return false;
    if( ! _request) _request = new (std::nothrow) xbuf;
    if(!_request){ _failRequest(HTTPCODE_TOO_LESS_RAM); return false; }
    size_t expected = _request->available() +
        (_HTTPmethod == HTTPmethodGET ? 4 : 5) + strlen(_URL->path) +
        strlen(_URL->query) + strlen(" HTTP/1.1\r\n") + 2;
    _request->write(_HTTPmethod == HTTPmethodGET ? "GET " : "POST ");
    _request->write(_URL->path);
    _request->write(_URL->query);
    _request->write(" HTTP/1.1\r\n");
    delete _URL;
    _URL = nullptr;
    header* hdr = _headers;
    while(hdr){
        expected += strlen(hdr->name) + strlen(hdr->value) + 3;
        _request->write(hdr->name);
        _request->write(':');
        _request->write(hdr->value);
        _request->write("\r\n");
        hdr = hdr->next;
    }
    delete _headers;
    _headers = nullptr;
    _request->write("\r\n");
    if(_request->available() != expected){
        _failRequest(HTTPCODE_TOO_LESS_RAM);
        return false;
    }

    return true;
}

//**************************************************************************************************************
size_t  asyncHTTPrequest::_send(){
    // ++++ ПРОВЕРКА ++++
    if( !_client ) {
        DEBUG_HTTP("*_send(): _client is NULL, aborting.\r\n");
        return 0;
    }
    // ++++++++++++++++++++++++++++++++

    if( ! _request) return 0;
    DEBUG_HTTP("_send() %d\r\n", _request->available());
    if( ! _client->connected() || ! _client->canSend()){
        DEBUG_HTTP("*can't send\r\n");
        return 0;
    }
    size_t supply = _request->available();
    size_t demand = _client->space();
    if(supply > demand) supply = demand;
    size_t sent = 0;
    uint8_t temp[100];
    while(supply){
        size_t chunk = supply < 100 ? supply : 100;
        supply -= _request->read(temp, chunk);
        sent += _client->add((char*)temp, chunk);
    }
    if(_request->available() == 0){
        delete _request;
        _request = nullptr;
    }
    _client->send();
    DEBUG_HTTP("*sent %d\r\n", sent);
    _lastActivity = millis(); 
    return sent;
}

void asyncHTTPrequest::_failRequest(int code){
    _HTTPcode = code;
    _requestEndTime = millis();
    _lastActivity = 0;
    _timeout = 0;
    _setReadyState(readyStateDone);
    if(_client) _client->abort();
}

//**************************************************************************************************************
void  asyncHTTPrequest::_setReadyState(readyStates newState){
    if(_readyState != newState){
        _readyState = newState;          
        DEBUG_HTTP("_setReadyState(%d)\r\n", _readyState);
        if(_readyStateChangeCB){
            _readyStateChangeCB(_readyStateChangeCBarg, this, _readyState);
        }
    } 
}

//**************************************************************************************************************
void  asyncHTTPrequest::_processChunks(){
    while(_chunks->available()){
        DEBUG_HTTP("_processChunks() %.16s... (%d)\r\n", _chunks->peekString(16).c_str(), _chunks->available());
        size_t _chunkRemaining = _contentLength - _contentRead - _response->available();
        const size_t availableChunk = _chunks->available();
        const size_t expected = _chunkRemaining < availableChunk ? _chunkRemaining : availableChunk;
        const size_t copied = _response->write(_chunks, expected);
        if(copied != expected){ _failRequest(HTTPCODE_TOO_LESS_RAM); return; }
        _chunkRemaining -= copied;
        if(_chunks->indexOf("\r\n") == -1){
            return;
        }
        String chunkHeader = _chunks->readStringUntil("\r\n");
        DEBUG_HTTP("*getChunkHeader %.16s... (%d)\r\n", chunkHeader.c_str(), chunkHeader.length());
        size_t chunkLength = strtol(chunkHeader.c_str(),nullptr,16);
        _contentLength += chunkLength;
        if(chunkLength == 0){
            char* connectionHdr = respHeaderValue("connection");
            if(connectionHdr && (strcasecmp_P(connectionHdr,PSTR("disconnect")) == 0)){
                DEBUG_HTTP("*all chunks received - closing TCP\r\n");
                _client->close();
            }
            else {
                DEBUG_HTTP("*all chunks received - no disconnect\r\n"); 
            }
            _requestEndTime = millis();
            _lastActivity = 0;
            _timeout = 0;
            _setReadyState(readyStateDone);
            return;
        }
    }
}

/*______________________________________________________________________________________________________________

EEEEE   V   V   EEEEE   N   N   TTTTT         H   H    AAA    N   N   DDDD    L       EEEEE   RRRR     SSS
E       V   V   E       NN  N     T           H   H   A   A   NN  N   D   D   L       E       R   R   S 
EEE     V   V   EEE     N N N     T           HHHHH   AAAAA   N N N   D   D   L       EEE     RRRR     SSS
E        V V    E       N  NN     T           H   H   A   A   N  NN   D   D   L       E       R  R        S
EEEEE     V     EEEEE   N   N     T           H   H   A   A   N   N   DDDD    LLLLL   EEEEE   R   R    SSS 
_______________________________________________________________________________________________________________*/

//**************************************************************************************************************
void  asyncHTTPrequest::_onConnect(AsyncClient* client){
    DEBUG_HTTP("_onConnect handler\r\n");
    _seize;
    _client = client;
    _setReadyState(readyStateOpened);
    _response = new (std::nothrow) xbuf;
    if(!_response){
        _failRequest(HTTPCODE_TOO_LESS_RAM);
        _release;
        return;
    }
    _contentLength = 0;
    _contentRead = 0;
    _chunked = false;
    _client->onAck([](void* obj, AsyncClient* client, size_t len, uint32_t time){((asyncHTTPrequest*)(obj))->_send();}, this);
    _client->onData([](void* obj, AsyncClient* client, void* data, size_t len){((asyncHTTPrequest*)(obj))->_onData(data, len);}, this);
    if(_client->canSend()){
        _send();
    }
    _lastActivity = millis();
    _release;
}

//**************************************************************************************************************
void  asyncHTTPrequest::_onPoll(AsyncClient* client){
    _seize;
    if(_timeout && (millis() - _lastActivity) > (_timeout * 1000)){
        _client->close();
        _HTTPcode = HTTPCODE_TIMEOUT;
        DEBUG_HTTP("_onPoll timeout\r\n");
    }
    if(_onDataCB && available()){
        _onDataCB(_onDataCBarg, this, available());
    } 
    _release;     
}

//**************************************************************************************************************
void  asyncHTTPrequest::_onError(AsyncClient* client, int8_t error){
    DEBUG_HTTP("_onError handler error=%d\r\n", error);
    if(_HTTPcode >= 0) _HTTPcode = error;
}

//**************************************************************************************************************
void asyncHTTPrequest::_onDisconnect(AsyncClient* client) {
    DEBUG_HTTP("_onDisconnect handler\r\n");
    _seize;
    
    // ЗАЩИТА: проверяем, не вызвался ли уже этот метод
    if (!_client) {
        _release;
        return;
    }
    
    if(_readyState < readyStateOpened){
        _HTTPcode = HTTPCODE_NOT_CONNECTED;
    }
    else if (_HTTPcode > 0 && 
            (_readyState < readyStateHdrsRecvd || (_contentRead + _response->available()) < _contentLength)) {
        _HTTPcode = HTTPCODE_CONNECTION_LOST;
    }
    
    // БЕЗОПАСНОЕ УДАЛЕНИЕ: запоминаем указатель и обнуляем
    AsyncClient* clientToDelete = _client;
    _client = nullptr;
    
    delete clientToDelete;
    delete[] _connectedHost;
    _connectedHost = nullptr;
    _connectedPort = -1;
    _requestEndTime = millis();
    _lastActivity = 0;
    _setReadyState(readyStateDone);
    _release;
}

//**************************************************************************************************************
void  asyncHTTPrequest::_onData(void* Vbuf, size_t len){
    DEBUG_HTTP("_onData handler %.16s... (%d)\r\n",(char*) Vbuf, len);
    _seize;
    _lastActivity = millis();
    if(_readyState == readyStateDone || !_response){ _release; return; }
    const size_t buffered = _response->available() + (_chunks ? _chunks->available() : 0);
    if(buffered > _maxResponseBufferBytes || len > _maxResponseBufferBytes - buffered){
        _failRequest(HTTPCODE_RESPONSE_TOO_LARGE);
        _release;
        return;
    }

                // Transfer data to xbuf

    if(_chunks){
        if(_chunks->write((uint8_t*)Vbuf, len) != len){
            _failRequest(HTTPCODE_TOO_LESS_RAM);
            _release;
            return;
        }
        _processChunks();
        if(_HTTPcode < 0){ _release; return; }
    }
    else {
        if(_response->write((uint8_t*)Vbuf, len) != len){
            _failRequest(HTTPCODE_TOO_LESS_RAM);
            _release;
            return;
        }
    }

                // if headers not complete, collect them.
                // if still not complete, just return.

    if(_readyState == readyStateOpened){
        if( ! _collectHeaders()){
            _release;
            return;
        }
    }

                // If there's data in the buffer and not Done,
                // advance readyState to Loading.

    if(_response->available() && _readyState != readyStateDone){
        _setReadyState(readyStateLoading);
    }

                // If not chunked and all data read, close it up.

    if( ! _chunked && (_response->available() + _contentRead) >= _contentLength){
        char* connectionHdr = respHeaderValue("connection");
        if(connectionHdr && (strcasecmp_P(connectionHdr,PSTR("disconnect")) == 0)){
            DEBUG_HTTP("*all data received - closing TCP\r\n");
            _client->close();
        }
        else {
            DEBUG_HTTP("*all data received - no disconnect\r\n");
        }
        _requestEndTime = millis();
        _lastActivity = 0;
        _timeout = 0;
        _setReadyState(readyStateDone);        
    }

                // If onData callback requested, do so.

    if(_onDataCB && available()){
        _onDataCB(_onDataCBarg, this, available());
    }
    _release;            
          
}

//**************************************************************************************************************
bool  asyncHTTPrequest::_collectHeaders(){
    DEBUG_HTTP("_collectHeaders()\r\n");

            // Loop to parse off each header line.
            // Drop out and return false if no \r\n (incomplete)

    do {
        String headerLine = _response->readStringUntil("\r\n");

            // If no line, return false.

        if( ! headerLine.length()){
            return false;
        }  

            // If empty line, all headers are in, advance readyState.
           
        if(headerLine.length() == 2){
            _setReadyState(readyStateHdrsRecvd);
        }

            // If line is HTTP header, capture HTTPcode.

        else if(headerLine.substring(0,7) == "HTTP/1."){
            _HTTPcode = headerLine.substring(9, headerLine.indexOf(' ', 9)).toInt();
        }

            // Ordinary header, add to header list.

        else {
            int colon = headerLine.indexOf(':');
            if(colon != -1){
                String name = headerLine.substring(0, colon);
                name.trim();
                String value = headerLine.substring(colon+1);
                value.trim();
                if(!_addHeader(name.c_str(), value.c_str())) return false;
            }   
        } 
    } while(_readyState == readyStateOpened); 

            // If content-Length header, set _contentLength

    header *hdr = _getHeader("Content-Length");
    if(hdr){
        _contentLength = strtol(hdr->value,nullptr,10);
    }

            // If chunked specified, try to set _contentLength to size of first chunk

    hdr = _getHeader("Transfer-Encoding"); 
    if(hdr && strcasecmp_P(hdr->value, PSTR("chunked")) == 0){
        DEBUG_HTTP("*transfer-encoding: chunked\r\n");
        _chunked = true;
        _contentLength = 0;
        _chunks = new (std::nothrow) xbuf;
        if(!_chunks){ _failRequest(HTTPCODE_TOO_LESS_RAM); return false; }
        const size_t expected = _response->available();
        if(_chunks->write(_response, expected) != expected){
            _failRequest(HTTPCODE_TOO_LESS_RAM);
            return false;
        }
        _processChunks();
        if(_HTTPcode < 0) return false;
    }         

    
    return true;
}      
        

/*_____________________________________________________________________________________________________________

                        H   H  EEEEE   AAA   DDDD   EEEEE  RRRR    SSS
                        H   H  E      A   A  D   D  E      R   R  S   
                        HHHHH  EEE    AAAAA  D   D  EEE    RRRR    SSS
                        H   H  E      A   A  D   D  E      R  R       S
                        H   H  EEEEE  A   A  DDDD   EEEEE  R   R   SSS
______________________________________________________________________________________________________________*/

//**************************************************************************************************************
void	asyncHTTPrequest::setReqHeader(const char* name, const char* value){
    if(_readyState <= readyStateOpened && _headers){
        _addHeader(name, value);
    }
}

//**************************************************************************************************************
void	asyncHTTPrequest::setReqHeader(const char* name, const __FlashStringHelper* value){
    if(_readyState <= readyStateOpened && _headers){
        char* _value = _charstar(value);
        if(_value) _addHeader(name, _value);
        delete[] _value;
    }
}

//**************************************************************************************************************
void	asyncHTTPrequest::setReqHeader(const __FlashStringHelper *name, const char* value){
    if(_readyState <= readyStateOpened && _headers){
        char* _name = _charstar(name);
        if(_name) _addHeader(_name, value);
        delete[] _name;
    }
}

//**************************************************************************************************************
void	asyncHTTPrequest::setReqHeader(const __FlashStringHelper *name, const __FlashStringHelper* value){
    if(_readyState <= readyStateOpened && _headers){
        char* _name = _charstar(name);
        char* _value = _charstar(value);
        if(_name && _value) _addHeader(_name, _value);
        delete[] _name;
        delete[] _value;
    }
}

//**************************************************************************************************************
void	asyncHTTPrequest::setReqHeader(const char* name, int32_t value){
    if(_readyState <= readyStateOpened && _headers){
        setReqHeader(name, String(value).c_str());
    }
}

//**************************************************************************************************************
void	asyncHTTPrequest::setReqHeader(const __FlashStringHelper *name, int32_t value){
    if(_readyState <= readyStateOpened && _headers){
        char* _name = _charstar(name);
        if(_name) setReqHeader(_name, String(value).c_str());
        delete[] _name;
    }
}

//**************************************************************************************************************
int		asyncHTTPrequest::respHeaderCount(){
    if(_readyState < readyStateHdrsRecvd) return 0;                                            
    int count = 0;
    header* hdr = _headers;
    while(hdr){
        count++;
        hdr = hdr->next;
    }
    return count;
}

//**************************************************************************************************************
char*   asyncHTTPrequest::respHeaderName(int ndx){
    if(_readyState < readyStateHdrsRecvd) return nullptr;      
    header* hdr = _getHeader(ndx);
    if ( ! hdr) return nullptr;
    return hdr->name;
}

//**************************************************************************************************************
char*   asyncHTTPrequest::respHeaderValue(const char* name){
    if(_readyState < readyStateHdrsRecvd) return nullptr;      
    header* hdr = _getHeader(name);
    if( ! hdr) return nullptr;
    return hdr->value;
}

//**************************************************************************************************************
char*   asyncHTTPrequest::respHeaderValue(const __FlashStringHelper *name){
    if(_readyState < readyStateHdrsRecvd) return nullptr;
    char* _name = _charstar(name);      
    header* hdr = _getHeader(_name);
    delete[] _name;
    if( ! hdr) return nullptr;
    return hdr->value;
}

//**************************************************************************************************************
char*   asyncHTTPrequest::respHeaderValue(int ndx){
    if(_readyState < readyStateHdrsRecvd) return nullptr;      
    header* hdr = _getHeader(ndx);
    if ( ! hdr) return nullptr;
    return hdr->value;
}

//**************************************************************************************************************
bool	asyncHTTPrequest::respHeaderExists(const char* name){
    if(_readyState < readyStateHdrsRecvd) return false;      
    header* hdr = _getHeader(name);
    if ( ! hdr) return false;
    return true;
}

//**************************************************************************************************************
bool	asyncHTTPrequest::respHeaderExists(const __FlashStringHelper *name){
    if(_readyState < readyStateHdrsRecvd) return false;
    char* _name = _charstar(name);      
    header* hdr = _getHeader(_name);
    delete[] _name;
    if ( ! hdr) return false;
    return true;
}

//**************************************************************************************************************
String  asyncHTTPrequest::headers(){
    _seize;
    String _response = "";
    header* hdr = _headers;
    while(hdr){
        _response += hdr->name;
        _response += ':';
        _response += hdr->value;
        _response += "\r\n";
        hdr = hdr->next;
    }
    _response += "\r\n";
    _release;
    return _response;
}

//**************************************************************************************************************
asyncHTTPrequest::header*  asyncHTTPrequest::_addHeader(const char* name, const char* value){
    _seize;
    if(!name || !value){ _release; return nullptr; }
    size_t bytes = strlen(name) + strlen(value);
    size_t count = 1;
    for(header* current = _headers; current; current = current->next){
        if(strcasecmp(name, current->name) != 0){
            bytes += strlen(current->name) + strlen(current->value);
            count++;
        }
    }
    if(bytes > 4096 || count > 64){
        _failRequest(HTTPCODE_RESPONSE_TOO_LARGE);
        _release;
        return nullptr;
    }
    header* added = new (std::nothrow) header;
    if(added){
        added->name = new (std::nothrow) char[strlen(name)+1];
        added->value = new (std::nothrow) char[strlen(value)+1];
    }
    if(!added || !added->name || !added->value){
        delete added;
        _failRequest(HTTPCODE_TOO_LESS_RAM);
        _release;
        return nullptr;
    }
    strcpy(added->name, name);
    strcpy(added->value, value);
    header** link = &_headers;
    while(*link){
        if(strcasecmp(name, (*link)->name) == 0){
            header* old = *link;
            *link = old->next;
            old->next = nullptr;
            delete old;
        } else {
            link = &(*link)->next;
        }
    }
    *link = added;
    _release;
    return added;
}

//**************************************************************************************************************
asyncHTTPrequest::header* asyncHTTPrequest::_getHeader(const char* name){
    _seize;
    header* hdr = _headers;
    while (hdr) {
        if(strcasecmp(name, hdr->name) == 0) break;
        hdr = hdr->next;
    }
    _release;
    return hdr;
}

//**************************************************************************************************************
asyncHTTPrequest::header* asyncHTTPrequest::_getHeader(int ndx){
    _seize;
    header* hdr = _headers;
    while (hdr) {
        if( ! ndx--) break;
        hdr = hdr->next; 
    }
    _release;
    return hdr;
}

//**************************************************************************************************************
char* asyncHTTPrequest::_charstar(const __FlashStringHelper * str){
  if( ! str) return nullptr;
  char* ptr = new (std::nothrow) char[strlen_P((PGM_P)str)+1];
  if(!ptr){ _failRequest(HTTPCODE_TOO_LESS_RAM); return nullptr; }
  strcpy_P(ptr, (PGM_P)str);
  return ptr;
}
