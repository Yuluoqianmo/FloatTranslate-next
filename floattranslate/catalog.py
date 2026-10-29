"""Model catalogs from compatible gateways; IDs are never rewritten or guessed."""
import hashlib
import json
from urllib.parse import parse_qsl, urlsplit

from .settings import config_dir


class ModelList(list):
    def __init__(self, values=(), *, warning='', types=None):
        super().__init__(values)
        self.warning = warning
        self.types = types or {}


def model_page(data, protocol):
    """Return actual model IDs and pagination metadata from common envelopes."""
    metadata = {}
    payload = data
    for _ in range(5):
        if isinstance(payload,list):
            rows = payload
            break
        if not isinstance(payload,dict):
            return [],metadata,False
        metadata.update({k:v for k,v in payload.items() if k not in ('data','models','items','list','records','result')})
        for key in ('pagination','meta'):
            if isinstance(payload.get(key),dict):
                metadata.update(payload[key])
        for key in ('data','models','items','list','records','result'):
            if isinstance(payload.get(key),(list,dict)):
                payload = payload[key]
                break
        else:
            return [],metadata,False
    else:
        return [],metadata,False
    result=[]
    for row in rows:
        if isinstance(row,str):
            name=row
        elif isinstance(row,dict):
            if protocol=='google' and row.get('supportedGenerationMethods') and 'generateContent' not in row['supportedGenerationMethods']:
                continue
            name=next((row[k] for k in ('id','slug','model_id','model','name') if isinstance(row.get(k),str) and row[k].strip()),'')
        else:
            continue
        if isinstance(name,str) and name.strip():
            result.append(name.removeprefix('models/') if protocol=='google' else name)
    return result,metadata,True


def model_types(data):
    result={}
    def visit(node,depth=0):
        if depth>6:
            return
        if isinstance(node,list):
            for row in node:
                if isinstance(row,dict):
                    name=next((row[k] for k in ('id','slug','model_id','model','name') if isinstance(row.get(k),str) and row[k]),'')
                    types=row.get('supported_endpoint_types')
                    if name and isinstance(types,list):
                        result[name]=[t for t in types if isinstance(t,str)]
        elif isinstance(node,dict):
            for key in ('data','models','items','list','records','result'):
                if key in node:
                    visit(node[key],depth+1)
    visit(data)
    return result


def next_models_page(meta,protocol,rows,params,base_url):
    """Pagination follows only this exact models endpoint, never external links."""
    if protocol=='google' and meta.get('nextPageToken'):
        return {'pageSize':1000,'pageToken':str(meta['nextPageToken'])}
    if meta.get('has_more') and meta.get('last_id'):
        cursor=meta['last_id']
        return {'limit':1000,'after_id' if protocol=='anthropic' else 'after':str(cursor)}
    for field in ('next_cursor','nextCursor'):
        if meta.get(field):
            return {'cursor':str(meta[field])}
    next_page=meta.get('next_page')
    if isinstance(next_page,int) and not isinstance(next_page,bool) and next_page>0:
        return {'page':next_page,**({'page_size':meta['page_size']} if isinstance(meta.get('page_size'),int) else {})}
    current=meta.get('current_page',meta.get('page'))
    pages=meta.get('total_pages',meta.get('last_page'))
    if isinstance(current,int) and isinstance(pages,int) and 0<current<pages:
        return {'page':current+1,**({'page_size':meta['page_size']} if isinstance(meta.get('page_size'),int) else {})}
    link=meta.get('next') or (meta.get('links',{}).get('next') if isinstance(meta.get('links'),dict) else None)
    if isinstance(link,dict):
        link=link.get('href')
    if isinstance(link,str) and link:
        from urllib.parse import urljoin
        target=urlsplit(urljoin(base_url+'/models',link))
        endpoint=urlsplit(base_url+'/models')
        if (target.scheme,target.netloc,target.path)==(endpoint.scheme,endpoint.netloc,endpoint.path):
            pairs=dict(parse_qsl(target.query))
            if pairs and set(pairs)<= {'page','page_size','per_page','limit','offset','after','before','cursor','pageToken','after_id'}:
                return pairs
    if meta.get('has_more') and rows:
        return {'limit':1000,'after_id' if protocol=='anthropic' else 'after':rows[-1]}
    return None


def catalog_identity(connection):
    # Key-scoped cache: two credentials at one gateway may expose different IDs.
    return hashlib.sha256((connection.provider+'|'+connection.base_url+'|'+connection.protocol+'|'+connection.auth_mode+'|'+connection.key).encode()).hexdigest()


def load_catalog(connection):
    try:
        data=json.loads((config_dir()/'model-catalogs.json').read_text('utf-8'))
        values=data.get(catalog_identity(connection),[])
        types={}
        if isinstance(values,dict):
            types=values.get('types',{})
            values=values.get('models',[])
        return ModelList([v for v in values if isinstance(v,str) and v.strip()][:20000],types=types if isinstance(types,dict) else {}) if isinstance(values,list) else ModelList()
    except (OSError,ValueError,TypeError,AttributeError):
        return []


def save_catalog(connection,models):
    directory=config_dir()
    directory.mkdir(parents=True,exist_ok=True)
    try:
        data=json.loads((directory/'model-catalogs.json').read_text('utf-8'))
        if not isinstance(data,dict):
            data={}
    except (OSError,ValueError):
        data={}
    data[catalog_identity(connection)]={'models':list(models)[:20000],'types':getattr(models,'types',{})}
    # Keep a bounded number of endpoint/credential catalogs, no API keys stored.
    data=dict(list(data.items())[-32:])
    temp=directory/'model-catalogs.json.tmp'
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
    temp.replace(directory/'model-catalogs.json')


def load_enabled(connection,current=''):
    try:
        data=json.loads((config_dir()/'enabled-models.json').read_text('utf-8'))
        values=data.get(catalog_identity(connection),[])
        if not isinstance(values,list):
            values=[]
    except (OSError,ValueError,TypeError,AttributeError):
        values=[]
    return list(dict.fromkeys([v for v in values if isinstance(v,str) and v.strip()]+([current] if current else [])))


def save_enabled(connection,values,current=''):
    directory=config_dir()
    directory.mkdir(parents=True,exist_ok=True)
    try:
        data=json.loads((directory/'enabled-models.json').read_text('utf-8'))
        if not isinstance(data,dict):
            data={}
    except (OSError,ValueError):
        data={}
    data[catalog_identity(connection)]=list(dict.fromkeys([v for v in values if isinstance(v,str) and v.strip()]+([current] if current else [])))
    data=dict(list(data.items())[-32:])
    temp=directory/'enabled-models.json.tmp'
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
    temp.replace(directory/'enabled-models.json')
