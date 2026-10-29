import json
from dataclasses import replace

import httpx
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from floattranslate.catalog import ModelList, load_catalog, save_catalog
from floattranslate.dialogs import Preferences
from floattranslate.model_picker import ModelPicker
from floattranslate.providers import Connection, ModelClient, ProviderError, resolve
from floattranslate.settings import Settings, SecretStore


@pytest.mark.parametrize('payload',[
    {'data':[{'id':'a'},{'id':'b'}],'models':{'count':2}},
    {'models':[{'slug':'a'},{'id':'b'}]},
    {'data':{'items':[{'model':'a'},{'model_id':'b'}]}},
    {'result':{'records':['a','b']}},
    ['a','b'],
])
def test_gateway_envelopes_preserve_complete_ids(payload):
    client=ModelClient(Connection('custom','https://test.example/v1','openai','synthetic'),httpx.MockTransport(lambda r:httpx.Response(200,json=payload)))
    try:
        assert client.models()==['a','b']
    finally:
        client.close()


@pytest.mark.parametrize('style',['cursor','openai','page','links'])
def test_gateway_pagination(style):
    calls=[]
    def handler(request):
        calls.append(request)
        if len(calls)==2:
            return httpx.Response(200,json={'data':[{'id':'b'}]})
        extra={'cursor':{'next_cursor':'two','has_more':True},'openai':{'has_more':True,'last_id':'a'},
               'page':{'pagination':{'current_page':1,'total_pages':2}},
               'links':{'links':{'next':'https://test.example/v1/models?page=2'}}}[style]
        return httpx.Response(200,json={'data':[{'id':'a'}],**extra})
    client=ModelClient(Connection('custom','https://test.example/v1','openai','synthetic'),httpx.MockTransport(handler))
    try:
        assert client.models()==['a','b']
        assert len(calls)==2
        assert calls[-1].url.params.get({'cursor':'cursor','openai':'after','page':'page','links':'page'}[style]) in ('two','a','2')
    finally:
        client.close()


def test_no_100_model_truncation_and_repeated_page_warning():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'data':[{'id':f'model-{i:04}'} for i in range(350)],'next_cursor':'same'})
    client=ModelClient(Connection('custom','https://test.example/v1','openai','synthetic'),httpx.MockTransport(handler))
    try:
        result=client.models()
        assert len(result)==350 and result.warning and len(calls)==2
    finally:
        client.close()


def test_partial_failure_keeps_successful_page():
    calls=[]
    def handler(r):
        calls.append(r)
        return httpx.Response(200,json={'data':['a'],'next_cursor':'two'}) if len(calls)==1 else httpx.Response(500,text='synthetic-secret')
    client=ModelClient(Connection('custom','https://test.example/v1','openai','synthetic-secret'),httpx.MockTransport(handler))
    try:
        result=client.models()
        assert result==['a'] and result.warning and 'synthetic-secret' not in result.warning
    finally:
        client.close()


def test_external_pagination_never_receives_key():
    calls=[]
    def handler(r):
        calls.append(r)
        return httpx.Response(200,json={'data':['a'],'next':'https://other.example/models?page=2'})
    client=ModelClient(Connection('custom','https://test.example/v1','openai','synthetic'),httpx.MockTransport(handler))
    try:
        assert client.models()==['a'] and len(calls)==1
    finally:
        client.close()


@pytest.mark.parametrize('base', ['https://test.example','https://test.example/v1','https://test.example/v1/models','https://test.example/v1/chat/completions','https://test.example/v1/responses'])
def test_full_endpoint_normalization(base):
    assert resolve('custom',base,'synthetic').base_url=='https://test.example/v1'


def test_response_protocol_and_auth_override():
    calls=[]
    def handler(r):
        calls.append(r)
        return httpx.Response(200,json={'output':[{'type':'message','content':[{'type':'output_text','text':'OK'}]}]})
    connection=resolve('custom','https://test.example','synthetic',protocol='responses',auth_mode='x-api-key')
    client=ModelClient(connection,httpx.MockTransport(handler))
    try:
        assert client.generate('custom-model','Reply OK','test')=='OK'
        assert calls[0].url.path=='/v1/responses'
        assert calls[0].headers['x-api-key']=='synthetic' and 'authorization' not in calls[0].headers
        assert json.loads(calls[0].content)['model']=='custom-model'
    finally:
        client.close()


def test_model_cache_is_key_endpoint_and_protocol_scoped(tmp_path,monkeypatch):
    monkeypatch.setenv('FLOATTRANSLATE_CONFIG_DIR',str(tmp_path))
    connection=Connection('custom','https://test.example/v1','openai','do-not-store-this-key')
    save_catalog(connection,['a','b'])
    assert load_catalog(connection)==['a','b']
    assert not load_catalog(replace(connection,key='another-key'))
    assert not load_catalog(replace(connection,protocol='responses'))
    assert not load_catalog(replace(connection,base_url='https://other.example/v1'))
    assert 'do-not-store-this-key' not in (tmp_path/'model-catalogs.json').read_text('utf-8')


def test_picker_search_and_manual_id_are_independent():
    app=QApplication.instance() or QApplication([])
    picker=ModelPicker([f'model-{i:04}' for i in range(350)],'manual-only')
    assert picker.list.count()==351 and picker.model_id()=='manual-only'
    picker.search.setText('0349')
    assert picker.list.count()==1 and picker.model_id()=='manual-only'
    picker.list.setCurrentRow(0)
    assert picker.model_id()=='manual-only'
    picker.use_selected()
    assert picker.model_id()=='model-0349'
    picker.selected.setText('vendor/special-alias')
    picker.search.setText('not-found')
    assert picker.model_id()=='vendor/special-alias' and picker.list.count()==0
    picker.close()


def test_fetch_preserves_manual_id_and_stale_fetch_cannot_replace_catalog(tmp_path,monkeypatch):
    monkeypatch.setenv('FLOATTRANSLATE_CONFIG_DIR',str(tmp_path))
    app=QApplication.instance() or QApplication([])
    pool=QThreadPool()
    dialog=Preferences('api',Settings(provider='custom',base_url='http://localhost:1234/v1',model='manual-only'),SecretStore(),pool,None)
    dialog._model_connection=dialog._resolve()
    models=ModelList([f'model-{i:04}' for i in range(350)])
    dialog._done((('models',dialog._revision),models,None))
    assert dialog.model.currentText()=='manual-only' and dialog.model.count()==350
    dialog.model.setCurrentIndex(349)
    assert dialog.model.currentText()=='model-0349'
    dialog.model.setEditText('another-manual-id')
    old=dialog._revision
    dialog.url.setText('http://localhost:1235/v1')
    dialog._done((('models',old),['wrong-connection-model'],None))
    assert 'wrong-connection-model' not in dialog.models_list
    assert dialog.model.currentText()=='another-manual-id'
    dialog.close()
