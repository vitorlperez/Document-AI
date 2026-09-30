# Spike F0.4 — pgvector / SQLAlchemy / psycopg3

Data: 2026-09-29. PoC executada em Postgres Docker descartável `pgvector/pgvector:0.8.2-pg16` (digest `sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc`). Sem código de produção e sem conectar a bancos do usuário.

## Resultado medido

`SQLAlchemy 2.0.52`, `psycopg 3.3.5`, pacote Python `pgvector 0.5.0`, extensão SQL `0.8.2`. `CREATE EXTENSION vector` permitido localmente. `Vector(1536)` inseriu lista Python; leitura voltou diretamente como **list de 1536 floats** (não ndarray nesta combinação). Ambos `type_coerce(list, Vector(1536))` com `.cosine_distance()` e `text()` + `bindparam("q", type_=Vector(1536))` fizeram `<=>`, distância 0/similaridade 1.0 para vetor idêntico. `SET hnsw.iterative_scan='strict_order'` aceito. Script terminou exit 0 e removeu a tabela.

Receita de registro: criar extensão em conexão inicial, descartar pool (`engine.dispose()`), então listener `connect` chama `pgvector.psycopg.register_vector(dbapi_connection)`. Em produção, migração cria extensão antes de registrar conexões. Não foi preciso fallback `cast(literal(...), Vector(1536))`; **não interpolar vetor em SQL**.

| Ambiente | CREATE EXTENSION | versão / iterative_scan | evidência |
|---|---|---|---|
| Docker descartável local | sim | 0.8.2 / sim | PoC abaixo executada exit 0 |
| Render | não medido | não medido | sem acesso a instância alvo |
| Railway | não medido | não medido | sem acesso a instância alvo |
| Oracle | não medido | não medido | sem acesso a instância alvo |

**F5 desbloqueada quanto ao contrato de bind; gate de disponibilidade por ambiente permanece pendente.** Não afirmar permissão nos hosts só porque o Docker local suporta. Conferir `select extversion` e iteratividade no banco alvo antes de ligar backend pgvector. A primeira execução do script assumia `.tolist()` e falhou (AttributeError); corrigida para `list(vector)`, conforme tipo real observado.

## PoC reproduzível

```sh
docker run -d --name integracoes-pgvector-spike -e POSTGRES_PASSWORD=spike-local -p 127.0.0.1:55439:5432 pgvector/pgvector:0.8.2-pg16
# Ao terminar: docker stop integracoes-pgvector-spike && docker rm integracoes-pgvector-spike
```

Credencial abaixo é fixa e exclusiva do container descartável local do spike. Nunca usar em ambientes reais.

```python
import json
from uuid import uuid4
import sqlalchemy, psycopg
from sqlalchemy import create_engine, event, MetaData, Table, Column, select, type_coerce, text, bindparam
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
from pgvector.psycopg import register_vector
engine=create_engine('postgresql+psycopg://postgres:spike-local@127.0.0.1:55439/postgres')
with engine.begin() as conn: conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
engine.dispose()
@event.listens_for(engine,'connect')
def connect(dbapi_connection, connection_record): register_vector(dbapi_connection)
t=Table('format_spike',MetaData(),Column('id',UUID,primary_key=True),Column('e',Vector(1536)))
e=[1.0]+[0.0]*1535
with engine.begin() as c:
 t.create(c,checkfirst=True); c.execute(t.insert().values(id=uuid4(),e=e))
 typed=c.execute(select(t.c.id, 1-t.c.e.cosine_distance(type_coerce(e,Vector(1536)))).order_by(t.c.e.cosine_distance(type_coerce(e,Vector(1536)))).limit(5)).all()
 raw=c.execute(text('select id, 1 - (e <=> :q) as score from format_spike order by e <=> :q limit 5').bindparams(bindparam('q',type_=Vector(1536))),{'q':e}).all()
 vector=c.execute(select(t.c.e).limit(1)).scalar_one()
 version=c.execute(text("select extversion from pg_extension where extname='vector'")).scalar_one()
 c.execute(text("SET hnsw.iterative_scan = 'strict_order'"))
 assert typed[0][1]==raw[0][1]==1.0
 assert len(list(vector))==1536 and all(isinstance(x,float) for x in list(vector))
 result={'sqlalchemy':sqlalchemy.__version__,'psycopg':psycopg.__version__,'pgvector':version,'type_coerce_score':typed[0][1],'typed_bind_score':raw[0][1],'read_type':type(vector).__name__,'length':len(vector),'hnsw_iterative_scan':True}
 t.drop(c)
print(json.dumps(result,indent=2))

```

Fontes: [pgvector-python oficial](https://github.com/pgvector/pgvector-python), [pgvector oficial](https://github.com/pgvector/pgvector).
