import streamlit as st
import pandas as pd
import datetime
import sqlite3
import time
import os
from zoneinfo import ZoneInfo

st.set_page_config(page_title="Sistema de Estudos & Carreira", layout="wide", page_icon="🛡️")

# -----------------------------------------------------------------------------
# BANCO DE DADOS DINÂMICO (CAMINHO ABSOLUTO FIXO)
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "estudos_master.db")

def hoje_local():
    """Data de hoje no horário do Recife (o servidor do Streamlit usa outro fuso)."""
    return datetime.datetime.now(ZoneInfo("America/Recife")).date()

# -----------------------------------------------------------------------------
# NOVO: GUARDA PERMANENTE NA NUVEM (Supabase)
# O Streamlit Cloud apaga os arquivos quando o app dorme ou reinicia. Por isso o
# banco é baixado da nuvem ao abrir e enviado de volta a cada gravação.
# -----------------------------------------------------------------------------
import base64 as _b64, zlib as _zlib
import requests as _req

def _nuvem_cfg():
    try:
        sec = st.secrets["nuvem"]
        url, chave, token = sec.get("url"), sec.get("chave_publica"), sec.get("token")
        if url and chave and token:
            return str(url).rstrip("/"), str(chave), str(token)
    except Exception:
        pass
    return None

def _nuvem_rpc(nome, payload):
    url, chave, _ = _nuvem_cfg()
    r = _req.post(f"{url}/rest/v1/rpc/{nome}", json=payload, timeout=25,
                  headers={"apikey": chave, "Authorization": f"Bearer {chave}", "Content-Type": "application/json"})
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    return r.json()

@st.cache_resource
def nuvem_estado():
    """Roda UMA vez quando o app liga: traz da nuvem a versão mais recente do banco."""
    _versao_leitura = "2026-10-20"  # muda a cada atualização importante: força reler a nuvem
    est = {"ativa": False, "status": "desligada", "ultima": None, "erro": ""}
    cfg = _nuvem_cfg()
    if not cfg:
        return est
    est["ativa"] = True
    try:
        r = _nuvem_rpc("ler_banco", {"p_token": cfg[2]})
        if r and r.get("dados"):
            conteudo = _zlib.decompress(_b64.b64decode(r["dados"]))
            with open(DB_PATH, "wb") as f:
                f.write(conteudo)
            est.update(status="ok", ultima=r.get("criado_em"))
        else:
            est.update(status="vazia")  # primeira vez: o banco local será enviado
    except Exception as e:
        # Sem conseguir ler a nuvem, NÃO enviamos nada (para não sobrescrever seus dados com um banco vazio)
        est.update(status="erro", erro=str(e))
    return est

def nuvem_enviar():
    """Envia o banco inteiro para a nuvem. Devolve (ok, mensagem)."""
    est = nuvem_estado()
    if not est["ativa"]:
        return False, "nuvem desligada"
    if est["status"] == "erro":
        return False, "envio bloqueado: o app não conseguiu ler a nuvem ao abrir"
    try:
        with open(DB_PATH, "rb") as f:
            dados = _b64.b64encode(_zlib.compress(f.read(), 9)).decode()
        r = _nuvem_rpc("salvar_banco", {"p_token": _nuvem_cfg()[2], "p_dados": dados})
        est.update(status="ok", ultima=(r or {}).get("criado_em"))
        return True, "ok"
    except Exception as e:
        return False, str(e)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

ORIENTACOES_PADRAO_PATH = os.path.join(BASE_DIR, "orientacoes_cfo.json")

def carregar_orientacoes_padrao(c):
    """Carrega as orientações que vêm com o app (orientacoes_cfo.json).
    Só grava quando o arquivo muda, e nunca substitui uma orientação que você editou."""
    if not os.path.exists(ORIENTACOES_PADRAO_PATH):
        return
    try:
        with open(ORIENTACOES_PADRAO_PATH, "rb") as f:
            conteudo = f.read()
        import hashlib, json
        assinatura = hashlib.sha1(conteudo).hexdigest()
        c.execute("SELECT valor FROM configuracoes WHERE chave = 'orientacoes_padrao_versao'")
        res = c.fetchone()
        if res and res[0] == assinatura:
            return
        dados = json.loads(conteudo.decode("utf-8"))
        for o in dados.get("orientacoes", []):
            materia, topico, texto = (str(o.get(k, "")).strip() for k in ("materia", "topico", "texto"))
            if materia and topico and texto:
                c.execute("""INSERT INTO orientacoes (materia, topico, texto, origem) VALUES (?, ?, ?, 'padrao')
                             ON CONFLICT(materia, topico) DO UPDATE SET texto = excluded.texto
                             WHERE orientacoes.origem = 'padrao'""", (materia, topico, texto))
        c.execute("INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES ('orientacoes_padrao_versao', ?)",
                  (assinatura,))
    except Exception:
        pass  # se o arquivo estiver com problema, o app continua funcionando sem ele

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS metas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT UNIQUE,
                    tipo TEXT,
                    ativa INTEGER DEFAULT 1
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS materias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meta_id INTEGER,
                    nome TEXT,
                    FOREIGN KEY(meta_id) REFERENCES metas(id) ON DELETE CASCADE
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS topicos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    materia_id INTEGER,
                    nome TEXT,
                    teoria INTEGER DEFAULT 0,
                    resumo INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'Pendente',
                    FOREIGN KEY(materia_id) REFERENCES materias(id) ON DELETE CASCADE
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS exercicios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT,
                    topico_id INTEGER,
                    acertos INTEGER,
                    erros INTEGER,
                    FOREIGN KEY(topico_id) REFERENCES topicos(id) ON DELETE CASCADE
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS configuracoes (
                    chave TEXT PRIMARY KEY,
                    valor TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS orientacoes (
                    materia TEXT,
                    topico TEXT,
                    texto TEXT,
                    PRIMARY KEY (materia, topico)
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS editais (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT UNIQUE,
                    conteudo TEXT,
                    ajustes TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT,
                    topico_id INTEGER,
                    minutos INTEGER,
                    origem TEXT DEFAULT 'app',
                    FOREIGN KEY(topico_id) REFERENCES topicos(id) ON DELETE CASCADE
                )''')
    # NOVO: notas das redações (critérios do edital CBMPE 002/2026, cargo de Oficial)
    c.execute('''CREATE TABLE IF NOT EXISTS redacoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT,
                    tema TEXT,
                    linhas INTEGER,
                    a1 REAL, a2 REAL, a3 REAL, a4 REAL,
                    total REAL,
                    zerada INTEGER DEFAULT 0,
                    motivo_zero TEXT,
                    comentario TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS cronometro_estado (
                    topico_id INTEGER PRIMARY KEY,
                    status TEXT,
                    fim_timestamp REAL,
                    segundos_pausados INTEGER
                )''')

    # NOVO: colunas do cronograma semanal (adicionadas só se ainda não existirem;
    # os dados que você já tem no banco não são apagados)
    colunas_existentes = [col[1] for col in c.execute("PRAGMA table_info(topicos)").fetchall()]
    novas_colunas = {
        "semana": "INTEGER",              # 1 a 20
        "dia": "INTEGER",                 # 0 = Segunda ... 4 = Sexta
        "ordem": "INTEGER",               # ordem do bloco dentro do dia
        "bloco": "TEXT",                  # Bloco 1, Bloco 2, Bloco 3
        "minutos_planejados": "INTEGER",  # duração prevista
        "minutos_estudados": "INTEGER DEFAULT 0"
    }
    for nome_col, tipo_col in novas_colunas.items():
        if nome_col not in colunas_existentes:
            c.execute(f"ALTER TABLE topicos ADD COLUMN {nome_col} {tipo_col}")

    # NOVO: marca de quem escreveu a orientação ('padrao' = veio com o app; 'usuario' = você editou)
    colunas_orient = [col[1] for col in c.execute("PRAGMA table_info(orientacoes)").fetchall()]
    if "origem" not in colunas_orient:
        c.execute("ALTER TABLE orientacoes ADD COLUMN origem TEXT DEFAULT 'usuario'")
    # Ajuste de títulos ao edital (só troca o nome; o progresso do bloco é mantido)
    for antigo, novo in (("Estatuto (Lei 6.783): disposições gerais, hierarquia e disciplina",
                          "Estatuto (Lei 6.783): hierarquia e disciplina"),
                         ("70 questões em 3 h + redação em 1 h", "70 questões + redação em 5 h")):
        c.execute("UPDATE topicos SET nome = REPLACE(nome, ?, ?) WHERE nome LIKE ?", (antigo, novo, f"%{antigo}%"))
        c.execute("UPDATE OR IGNORE orientacoes SET topico = REPLACE(topico, ?, ?) WHERE topico LIKE ? AND origem = 'usuario'",
                  (antigo, novo, f"%{antigo}%"))
        c.execute("DELETE FROM orientacoes WHERE topico LIKE ? AND origem = 'padrao'", (f"%{antigo}%",))
    c.execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES ('banco_criado_em', ?)",
              (datetime.datetime.now(ZoneInfo('America/Recife')).strftime('%d/%m/%Y %H:%M'),))
    carregar_orientacoes_padrao(c)

    # Auto-correção para "portugês" -> "Português" no banco
    c.execute("UPDATE materias SET nome = REPLACE(nome, 'portugês', 'português') WHERE nome LIKE '%portugês%'")
    c.execute("UPDATE materias SET nome = REPLACE(nome, 'Portugês', 'Português') WHERE nome LIKE '%Portugês%'")
    c.execute("UPDATE materias SET nome = REPLACE(nome, 'PORTUGÊS', 'PORTUGUÊS') WHERE nome LIKE '%PORTUGÊS%'")
    
    conn.commit()
    conn.close()

nuvem_estado()
init_db()

def normalizar_nome_materia(nome):
    if not nome:
        return nome
    nome_corrigido = str(nome).strip()
    nome_corrigido = nome_corrigido.replace('portugês', 'português')
    nome_corrigido = nome_corrigido.replace('Portugês', 'Português')
    nome_corrigido = nome_corrigido.replace('PORTUGÊS', 'PORTUGUÊS')
    return nome_corrigido

# -----------------------------------------------------------------------------
# CRONÔMETRO
# -----------------------------------------------------------------------------
def get_timer_state(topico_id, duracao_padrao_segundos):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT status, fim_timestamp, segundos_pausados FROM cronometro_estado WHERE topico_id = ?", (int(topico_id),))
    res = c.fetchone()
    conn.close()
    
    agora = time.time()
    
    if not res:
        return {'status': 'STOPPED', 'restante': duracao_padrao_segundos}
        
    status, fim_ts, seg_pausados = res
    
    if status == 'RODANDO':
        restante = int(fim_ts - agora)
        if restante <= 0:
            set_timer_stop(topico_id)
            return {'status': 'FINISHED', 'restante': 0}
        return {'status': 'RODANDO', 'restante': restante}
    
    elif status == 'PAUSADO':
        return {'status': 'PAUSADO', 'restante': seg_pausados}
        
    return {'status': 'STOPPED', 'restante': duracao_padrao_segundos}

def set_timer_start(topico_id, segundos_restantes):
    fim_ts = time.time() + segundos_restantes
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO cronometro_estado (topico_id, status, fim_timestamp, segundos_pausados)
        VALUES (?, 'RODANDO', ?, ?)
    """, (int(topico_id), fim_ts, segundos_restantes))
    conn.commit()
    conn.close()

def set_timer_pause(topico_id, segundos_restantes):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO cronometro_estado (topico_id, status, fim_timestamp, segundos_pausados)
        VALUES (?, 'PAUSADO', 0, ?)
    """, (int(topico_id), int(segundos_restantes)))
    conn.commit()
    conn.close()

def set_timer_stop(topico_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM cronometro_estado WHERE topico_id = ?", (int(topico_id),))
    conn.commit()
    conn.close()

# -----------------------------------------------------------------------------
# CÁLCULO DE NÍVEL DE DOMÍNIO
# -----------------------------------------------------------------------------
def calcular_nivel_materia(materia_id, conn):
    query_topicos = "SELECT status, teoria FROM topicos WHERE materia_id = ?"
    df_topicos = pd.read_sql_query(query_topicos, conn, params=(int(materia_id),))
    
    if df_topicos.empty:
        return 5.0
        
    total_topicos = len(df_topicos)
    concluidos = len(df_topicos[(df_topicos['status'] == 'Concluído') | (df_topicos['teoria'] == 1)])
    parciais = len(df_topicos[(df_topicos['status'] == 'Parcial') & (df_topicos['teoria'] == 0)])
    
    pct_teoria = ((concluidos + (0.5 * parciais)) / total_topicos) * 10.0
    
    query_ex = """
        SELECT e.acertos, e.erros 
        FROM exercicios e
        JOIN topicos t ON e.topico_id = t.id
        WHERE t.materia_id = ?
    """
    df_ex = pd.read_sql_query(query_ex, conn, params=(int(materia_id),))
    
    if df_ex.empty:
        return round(pct_teoria, 1)
        
    total_acertos = df_ex['acertos'].sum()
    total_erros = df_ex['erros'].sum()
    total_q = total_acertos + total_erros
    
    if total_q == 0:
        return round(pct_teoria, 1)
        
    taxa_acerto = total_acertos / total_q
    score_pratica = taxa_acerto * 10.0
    
    peso_questoes = min(1.0, total_q / 30.0) * 0.6
    peso_teoria = 1.0 - peso_questoes
    
    nivel_calculado = (pct_teoria * peso_teoria) + (score_pratica * peso_questoes)
    return round(nivel_calculado, 1)

def get_config(chave, valor_padrao):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else valor_padrao

def set_config(chave, valor):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES (?, ?)", (chave, str(valor)))
    conn.commit()
    conn.close()

# -----------------------------------------------------------------------------
# NOVO: CRONOGRAMA CFO CBMPE 2027 (20 semanas, de 12/10/2026 a 26/02/2027)
# -----------------------------------------------------------------------------
CRONO_META_NOME = "CFO CBMPE 2027"
CRONO_INICIO = datetime.date(2026, 10, 12)  # segunda-feira da semana 1
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"]

LEG, CF, ADM, DPM = "Legislação dos Militares de PE", "Direito Constitucional", "Direito Administrativo", "Direito Penal Militar"
PORT, RED, REV, SIM = "Língua Portuguesa", "Redação", "Revisão", "Simulados"
MAPA_ROTATIVO = {"Est": "Estatística", "Mat": "Matemática", "Fís": "Física", "Quím": "Química",
                 "Bio": "Biologia", "Info": "Informática", "Inglês/Espanhol": "Língua Estrangeira"}

_LEG = ["Estatuto (Lei 6.783): hierarquia e disciplina", "Estatuto: cargo e função, obrigações e deveres",
        "Estatuto: direitos, prerrogativas, férias e licenças", "Estatuto: situações especiais e proteção social",
        "Estatuto: desligamento, exclusão, tempo de serviço", "Cód. Disciplinar (Lei 11.817): regime disciplinar e transgressões",
        "Cód. Disciplinar: penas e medidas administrativas", "Cód. Disciplinar: processo, recursos, comissões recursais",
        "Cód. Disciplinar: cancelamento, recompensas, transgressões em espécie", "Decreto 50.014/2020",
        "Lei 15.187/2013 (CBMPE): generalidades e organização", "Lei 15.187/2013: atribuições e pessoal",
        "Lei 14.751/2023: princípios, competências, quadros", "Lei 14.751/2023: direitos, garantias, ingresso",
        "2ª passada: Estatuto + Cód. Disciplinar em questões", "2ª passada: Decreto, Lei 15.187 e Lei 14.751 em questões"]
# Constitucional: (terça, sexta) nas semanas ímpares; só terça nas pares
_CF = [("Constituição: conceito e classificação", "Poder constituinte"), ("Eficácia das normas; princípios fundamentais",),
       ("Direitos individuais (art. 5º) – parte 1", "Art. 5º – parte 2 e remédios constitucionais"), ("Direitos sociais e nacionalidade",),
       ("Direitos políticos e partidos", "Organização do Estado: federação e União"), ("Estados, Municípios e repartição de competências",),
       ("Administração Pública (arts. 37 a 41)", "Militares dos Estados (art. 42)"), ("Poder Legislativo",),
       ("Poder Executivo", "Poder Judiciário"), ("Funções essenciais à Justiça",),
       ("Estado de defesa e estado de sítio", "Segurança pública (art. 144) e Forças Armadas"), ("Ordem social",),
       ("Controle de constitucionalidade: difuso e concentrado", "ADI, ADC, ADO e ADPF"), ("Constituição do Estado de Pernambuco",),
       ("ECA (Lei 8.069/1990)", "Lei Maria da Penha e Estatuto da Juventude"), ("Súmulas, jurisprudência e questões AOCP",)]
_ADM = ["Estado, governo e administração; fontes", "Princípios da administração", "Centralização, descentralização e desconcentração",
        "Administração indireta", "Agentes públicos: espécies, cargo, emprego, função", "Agentes: provimento, vacância e acumulação",
        "Agentes: regime disciplinar e responsabilidades", "Poderes: vinculado, discricionário, hierárquico, disciplinar, regulamentar",
        "Poder de polícia e abuso de poder", "Ato administrativo: requisitos e atributos", "Ato: classificação e espécies",
        "Ato: anulação, revogação e convalidação", "Serviços públicos", "Controle da administração",
        "Responsabilidade civil do Estado", "Questões AOCP"]
# Penal Militar: (quinta, sexta) nas semanas pares; só quinta nas ímpares
_DPM = [("Aplicação da lei penal militar",), ("Crime militar: art. 9º do CPM e Lei 13.491/2017", "Crime militar próprio e impróprio + questões"),
        ("Tempo e lugar do crime; dolo e culpa",), ("Excludentes de ilicitude e culpabilidade", "Imputabilidade penal"),
        ("Concurso de agentes",), ("Penas principais", "Penas acessórias"), ("Aplicação da pena e suspensão condicional",),
        ("Medidas de segurança", "Questões AOCP"), ("Ação penal militar",), ("Extinção da punibilidade", "Prescrição"),
        ("Crimes contra a autoridade e a disciplina",), ("Crimes contra o serviço e o dever militar", "Demais crimes contra o serviço militar"),
        ("Crimes contra a administração militar",), ("Crimes contra a pessoa e o patrimônio", "Crimes em tempo de guerra (visão geral)"),
        ("Súmulas do STF, STJ e STM",), ("Questões AOCP", "Questões AOCP e revisão")]
_ROT = [("Est: conceitos e apresentação de dados", "Mat: razão, proporção, porcentagem", "Quím: fogo e combustão"),
        ("Est: média, moda, mediana", "Fís: cinemática e MUV", "Bio: citologia e metabolismo"),
        ("Est: variância, desvio, CV, boxplot", "Info: segurança da informação", "Quím: átomo e tabela periódica"),
        ("Mat: juros, PA e PG", "Fís: dinâmica e Leis de Newton", "Bio: ecologia"),
        ("Est: probabilidade", "Inglês/Espanhol: interpretação e tempos verbais", "Quím: ligações e funções inorgânicas"),
        ("Mat: geometria plana e espacial", "Fís: hidrostática e empuxo", "Bio: saúde, doenças e primeiros socorros"),
        ("Est: variáveis aleatórias e distribuições", "Info: Windows 11, arquivos e backup", "Quím: soluções e estequiometria"),
        ("Mat: funções", "Fís: trabalho, energia e potência", "Bio: genética e biotecnologia"),
        ("Est: testes t, F e ANOVA (interpretação)", "Inglês/Espanhol: modais e condicionais", "Quím: produtos perigosos e oxirredução"),
        ("Mat: contagem e probabilidade", "Fís: termologia e gases", "Bio: fisiologia humana"),
        ("Est: regressão linear", "Info: Excel e Calc", "Quím: termoquímica, equilíbrio, pH e tampão"),
        ("Fís: eletrodinâmica (Lei de Ohm)", "Inglês/Espanhol: orações relativas e voz passiva", "Bio: biomas e problemas ambientais"),
        ("Est: questões AOCP", "Info: internet, nuvem, Word e Writer", "Quím: radioatividade e orgânica básica"),
        ("Mat: trigonometria e geometria analítica", "Fís: óptica e ondas", "Bio: questões AOCP"),
        ("Est: revisão e questões", "Inglês/Espanhol: questões", "Quím: questões AOCP"),
        ("Mat: questões mistas de Matemática e Física", "Info: questões", "Quím: questões mistas de Química e Biologia")]
_PORT = ["Interpretação, tipologia e gêneros textuais", "Classes de palavras I", "Classes de palavras II", "Funções do QUE e do SE",
         "Termos da oração", "Coordenação e subordinação", "Pontuação", "Concordância", "Regência e crase", "Colocação pronominal",
         "Ortografia e acentuação", "Coesão e relações semânticas", "Figuras de linguagem, significação e formação de palavras",
         "Variação linguística e interpretação", "Questões AOCP", "Questões AOCP"]

def gerar_cronograma_cfo():
    """Monta a lista de blocos de estudo das 20 semanas: (semana, dia, ordem, bloco, minutos, matéria, tópico)."""
    itens = []
    def add(sem, dia, ordem, bloco, minutos, materia, topico):
        itens.append((sem, dia, ordem, bloco, minutos, materia, topico))
    def rotativo(texto):
        prefixo, assunto = texto.split(": ", 1)
        return MAPA_ROTATIVO[prefixo], assunto

    # Semanas 1 a 16: fases 1 (base) e 2 (aprofundamento com questões)
    for i in range(16):
        s = i + 1
        add(s, 0, 1, "Bloco 1", 120, LEG, _LEG[i])
        add(s, 0, 2, "Bloco 2", 90, PORT, _PORT[i])
        add(s, 0, 3, "Bloco 3", 30, LEG, "Lei seca: " + _LEG[i])
        add(s, 1, 1, "Bloco 1", 120, CF, _CF[i][0])
        add(s, 1, 2, "Bloco 2", 90, *rotativo(_ROT[i][0]))
        add(s, 1, 3, "Bloco 3", 30, REV, "Caderno de erros")
        add(s, 2, 1, "Bloco 1", 120, ADM, _ADM[i])
        add(s, 2, 2, "Bloco 2", 90, *rotativo(_ROT[i][1]))
        add(s, 2, 3, "Bloco 3", 30, REV, "Caderno de erros")
        add(s, 3, 1, "Bloco 1", 60, DPM, _DPM[i][0])
        add(s, 3, 2, "Bloco 1", 60, LEG, "Continuação: " + _LEG[i])
        add(s, 3, 3, "Bloco 2", 90, *rotativo(_ROT[i][2]))
        add(s, 3, 4, "Bloco 3", 30, LEG, "Lei seca: " + _LEG[i])
        if s % 2 == 1:
            add(s, 4, 1, "Bloco 1", 120, CF, _CF[i][1])
        else:
            add(s, 4, 1, "Bloco 1", 120, DPM, _DPM[i][1])
        add(s, 4, 2, "Bloco 2", 90, RED, "Redação semanal (15 a 20 linhas, cronometrada)")
        add(s, 4, 3, "Bloco 3", 30, REV, "Revisão da semana")

    # Semanas 17, 19 e 20: fase 3 (revisão e simulados)
    b2 = {17: ((PORT, "Revisão e questões"), ("Estatística", "Revisão e questões"),
               ("Química", "Revisão de Química e Biologia"), ("Matemática", "Revisão de Matemática e Física")),
          19: ((PORT, "Revisão e questões"), ("Informática", "Revisão de Informática e Língua Estrangeira"),
               ("Estatística", "Revisão e questões"), ("Física", "Revisão de Física, Química e Biologia")),
          20: ((PORT, "Revisão leve"), ("Estatística", "Revisão leve"),
               ("Informática", "Revisão leve de Informática e Língua Estrangeira"), ("Matemática", "Exatas mistas: revisão leve"))}
    for s in (17, 19, 20):
        for dia, mat in enumerate((LEG, CF, ADM, DPM)):
            add(s, dia, 1, "Bloco 1", 120, mat, "Revisão geral + questões AOCP" if s < 20 else "Revisão leve")
            add(s, dia, 2, "Bloco 2", 90, *b2[s][dia])
            add(s, dia, 3, "Bloco 3", 30, REV, "Caderno de erros")
    add(17, 4, 1, "Simulado", 240, SIM, "Simulado 1: 70 questões + redação em 5 h")
    add(19, 4, 1, "Simulado", 240, SIM, "Simulado 2: 70 questões + redação em 5 h")
    add(20, 4, 1, "Bloco 1", 120, LEG, "Só lei seca, nada de conteúdo novo (prova no domingo, 28/02)")

    # Semana 18: Carnaval (semana reduzida, 8 h)
    add(18, 3, 1, "Bloco 1", 120, LEG, "Revisão (semana de Carnaval)")
    add(18, 3, 2, "Bloco 1", 120, DPM, "Revisão (semana de Carnaval)")
    add(18, 4, 1, "Bloco 1", 120, CF, "Revisão (semana de Carnaval)")
    add(18, 4, 2, "Bloco 2", 120, RED, "Redação (semana de Carnaval)")
    return itens

def nome_topico_crono(semana, dia, topico, inicio_crono=CRONO_INICIO):
    data_bloco = inicio_crono + datetime.timedelta(weeks=semana - 1, days=dia)
    return f"S{semana:02d} {DIAS_SEMANA[dia][:3]} {data_bloco:%d/%m} · {topico}"

def carregar_cronograma(conn, nome_objetivo, inicio_crono, itens, tipo="Concurso", substituir=False):
    """Cria o objetivo, as matérias e os tópicos de um cronograma.
    itens = lista de (semana, dia, ordem, bloco, minutos, matéria, tópico). Retorna quantos blocos foram criados."""
    c = conn.cursor()
    c.execute("SELECT id FROM metas WHERE nome = ?", (nome_objetivo,))
    existente = c.fetchone()
    if existente:
        if not substituir:
            return 0
        c.execute("DELETE FROM metas WHERE id = ?", (existente[0],))  # apaga matérias, tópicos e questões dele (CASCADE)
    c.execute("INSERT INTO metas (nome, tipo) VALUES (?, ?)", (nome_objetivo, tipo))
    meta_id = c.lastrowid
    ids_materias = {}
    total = 0
    for semana, dia, ordem, bloco, minutos, materia, topico in itens:
        materia = normalizar_nome_materia(materia)
        if materia not in ids_materias:
            c.execute("INSERT INTO materias (meta_id, nome) VALUES (?, ?)", (meta_id, materia))
            ids_materias[materia] = c.lastrowid
        c.execute("""INSERT INTO topicos (materia_id, nome, semana, dia, ordem, bloco, minutos_planejados, minutos_estudados)
                     VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                  (ids_materias[materia], nome_topico_crono(semana, dia, topico, inicio_crono),
                   semana, dia, ordem, bloco, minutos))
        total += 1
    conn.commit()
    set_config(f"cronograma_inicio_{meta_id}", inicio_crono.isoformat())
    return total

def carregar_cronograma_cfo(conn, substituir=False):
    return carregar_cronograma(conn, CRONO_META_NOME, CRONO_INICIO, gerar_cronograma_cfo(), "Concurso", substituir)

def ler_arquivo_cronograma(conteudo_bytes):
    """Lê e confere o arquivo .json de cronograma gerado pelo Claude.
    Retorna (dados, erros). 'dados' só vem preenchido se não houver erros."""
    import json
    erros = []
    try:
        dados = json.loads(conteudo_bytes.decode("utf-8-sig"))
    except Exception as e:
        return None, [f"O arquivo não é um JSON válido ({e})."]
    if not isinstance(dados, dict):
        return None, ["O arquivo não tem o formato esperado."]
    objetivo = str(dados.get("objetivo", "")).strip()
    if not objetivo:
        erros.append("Falta o campo 'objetivo' (nome do concurso).")
    try:
        inicio_crono = datetime.date.fromisoformat(str(dados.get("inicio", "")))
        if inicio_crono.weekday() != 0:
            erros.append("A data de 'inicio' precisa ser uma segunda-feira.")
    except ValueError:
        inicio_crono = None
        erros.append("O campo 'inicio' precisa ser uma data no formato AAAA-MM-DD.")
    blocos = dados.get("blocos")
    itens = []
    if not isinstance(blocos, list) or not blocos:
        erros.append("Falta a lista 'blocos' com os blocos de estudo.")
    else:
        for n, b in enumerate(blocos, start=1):
            try:
                semana, dia = int(b["semana"]), int(b["dia"])
                ordem, minutos = int(b.get("ordem", 1)), int(b["minutos"])
                materia, topico = str(b["materia"]).strip(), str(b["topico"]).strip()
                bloco = str(b.get("bloco", "Bloco")).strip()
            except (KeyError, TypeError, ValueError):
                erros.append(f"Bloco nº {n}: falta algum campo ou há valor inválido.")
                continue
            if semana < 1 or not (0 <= dia <= 4) or minutos <= 0 or not materia or not topico:
                erros.append(f"Bloco nº {n}: semana, dia (0 a 4), minutos, matéria ou tópico fora do padrão.")
                continue
            itens.append((semana, dia, ordem, bloco, minutos, materia, topico))
    if erros:
        return None, erros[:10]
    return {"objetivo": objetivo, "tipo": str(dados.get("tipo", "Concurso")), "inicio": inicio_crono,
            "data_prova": str(dados.get("data_prova", "")), "itens": itens}, []

def gerar_json_cronograma_cfo():
    """Exporta o cronograma CFO no mesmo formato do importador (serve de modelo)."""
    import json
    blocos = [{"semana": s, "dia": d, "ordem": o, "bloco": b, "minutos": m, "materia": mat, "topico": t}
              for s, d, o, b, m, mat, t in gerar_cronograma_cfo()]
    return json.dumps({"versao": 1, "objetivo": CRONO_META_NOME, "tipo": "Concurso",
                       "inicio": CRONO_INICIO.isoformat(), "data_prova": "2027-02-28", "blocos": blocos},
                      ensure_ascii=False, indent=1)

# -----------------------------------------------------------------------------
# NOVO: PLANEJADOR (o app distribui o tempo pelo peso, prioridade e conhecimento)
# -----------------------------------------------------------------------------
FATOR_PRIORIDADE = {"Alta": 1.5, "Média": 1.0, "Baixa": 0.65}
FATOR_CONHECIMENTO = {0: 1.6, 1: 1.45, 2: 1.3, 3: 1.15, 4: 1.0, 5: 0.85}
PESO_TOPICO = {"Alta": 3, "Média": 2, "Baixa": 1}
LEGENDA_CONHECIMENTO = {0: "não sei nada", 1: "muito pouco", 2: "pouco", 3: "razoável",
                        4: "bom", 5: "bom conhecimento e facilidade"}

def ler_arquivo_edital(dados):
    """Confere um edital (formato com 'materias'). Retorna (edital, erros)."""
    erros = []
    objetivo = str(dados.get("objetivo", "")).strip()
    if not objetivo:
        erros.append("Falta o campo 'objetivo' (nome do concurso).")
    try:
        data_prova = datetime.date.fromisoformat(str(dados.get("data_prova", "")))
    except ValueError:
        data_prova = None
        erros.append("O campo 'data_prova' precisa ser uma data no formato AAAA-MM-DD.")
    materias = []
    lista = dados.get("materias")
    if not isinstance(lista, list) or not lista:
        erros.append("Falta a lista 'materias'.")
        lista = []
    for n, m in enumerate(lista, start=1):
        try:
            nome = str(m["nome"]).strip()
            pontos = float(m.get("pontos", m.get("questoes", 0)))
        except (KeyError, TypeError, ValueError):
            erros.append(f"Matéria nº {n}: falta o nome ou os pontos.")
            continue
        prioridade = str(m.get("prioridade", "Média")).strip().capitalize().replace("Media", "Média")
        if prioridade not in FATOR_PRIORIDADE:
            prioridade = "Média"
        topicos = []
        for t in m.get("topicos", []):
            if isinstance(t, dict):
                tn, tp = str(t.get("nome", "")).strip(), str(t.get("prioridade", "Média")).strip().capitalize().replace("Media", "Média")
            else:
                tn, tp = str(t).strip(), "Média"
            if tn:
                topicos.append({"nome": tn, "prioridade": tp if tp in PESO_TOPICO else "Média"})
        if not nome or pontos <= 0:
            erros.append(f"Matéria nº {n}: nome vazio ou pontos igual a zero.")
            continue
        tipo = str(m.get("tipo", "")).strip().lower()
        if not topicos and tipo != "redacao":
            erros.append(f"Matéria '{nome}': lista de tópicos vazia.")
            continue
        materias.append({"nome": nome, "bloco": str(m.get("bloco", "")), "questoes": m.get("questoes"),
                         "pontos": pontos, "prioridade": prioridade, "tipo": tipo,
                         "conhecimento": max(0, min(5, int(m.get("conhecimento", 3)))) if str(m.get("conhecimento", 3)).isdigit() else 3,
                         "topicos": topicos})
    if erros:
        return None, erros[:10]
    return {"objetivo": objetivo, "tipo": str(dados.get("tipo", "Concurso")), "data_prova": data_prova.isoformat(),
            "banca": str(dados.get("banca", "")), "materias": materias}, []

def pesos_das_materias(materias, ajustes):
    """Peso de cada matéria = pontos x fator de prioridade x fator de conhecimento (redação fica de fora)."""
    pesos = {}
    for m in materias:
        if m["tipo"] == "redacao":
            continue
        aj = ajustes.get(m["nome"], {})
        prio = aj.get("prioridade", m["prioridade"])
        conh = int(aj.get("conhecimento", m["conhecimento"]))
        pesos[m["nome"]] = m["pontos"] * FATOR_PRIORIDADE[prio] * FATOR_CONHECIMENTO[conh]
    return pesos

def _distribuir_topicos(topicos, n_sessoes):
    """Divide os tópicos (em ordem) pelas sessões de uma matéria. Tópicos de prioridade Alta ganham mais sessões."""
    if n_sessoes <= 0 or not topicos:
        return []
    pesos = [PESO_TOPICO[t["prioridade"]] for t in topicos]
    if n_sessoes >= len(topicos):
        extras = n_sessoes - len(topicos)
        qtd = [1] * len(topicos)
        total_p = sum(pesos)
        for i in range(len(topicos)):
            qtd[i] += int(extras * pesos[i] / total_p)
        resto = n_sessoes - sum(qtd)
        for i in sorted(range(len(topicos)), key=lambda k: -pesos[k])[:resto]:
            qtd[i] += 1
        rotulos = []
        for t, q in zip(topicos, qtd):
            for k in range(q):
                if q == 1:
                    rotulos.append(t["nome"])
                elif k == q - 1:
                    rotulos.append(f"{t['nome']} (questões)")
                else:
                    rotulos.append(f"{t['nome']} (parte {k + 1})")
        return rotulos
    # menos sessões que tópicos: agrupa tópicos vizinhos, equilibrando o peso
    alvo = sum(pesos) / n_sessoes
    grupos, atual, acum = [], [], 0.0
    for i, t in enumerate(topicos):
        atual.append(t["nome"])
        acum += pesos[i]
        faltam_topicos = len(topicos) - i - 1
        faltam_grupos = n_sessoes - len(grupos) - 1
        if (acum >= alvo and faltam_grupos > 0) or faltam_topicos == faltam_grupos:
            if faltam_grupos > 0:
                grupos.append(" | ".join(atual))
                atual, acum = [], 0.0
    if atual:
        grupos.append(" | ".join(atual))
    return grupos

def gerar_cronograma_do_edital(edital, ajustes, inicio_crono, horas_dia, pct_revisao=0.15, com_simulados=True, primeiro_dia=None):
    """Monta os blocos (semana, dia, ordem, bloco, minutos, matéria, tópico) até a véspera da prova."""
    data_prova = datetime.date.fromisoformat(edital["data_prova"])
    materias = {m["nome"]: m for m in edital["materias"]}
    redacao = [m["nome"] for m in edital["materias"] if m["tipo"] == "redacao"]
    pesos = pesos_das_materias(edital["materias"], ajustes)
    soma_pesos = sum(pesos.values())
    if soma_pesos <= 0:
        return []
    cota = {n: p / soma_pesos for n, p in pesos.items()}
    prioridade_de = {m["nome"]: ajustes.get(m["nome"], {}).get("prioridade", m["prioridade"]) for m in edital["materias"]}
    minutos_dia = int(round(horas_dia * 60))

    dias = []
    d = inicio_crono
    while d < data_prova:
        if d.weekday() < 5 and (primeiro_dia is None or d >= primeiro_dia):
            dias.append(d)
        d += datetime.timedelta(days=1)
    if not dias:
        return []
    n_semanas = (dias[-1] - inicio_crono).days // 7 + 1
    sem_revisao = 0 if n_semanas < 4 else max(1, round(n_semanas * pct_revisao))
    primeira_revisao = n_semanas - sem_revisao + 1
    ultimo_dia_semana = {}
    for d in dias:
        ultimo_dia_semana[(d - inicio_crono).days // 7 + 1] = d
    dias_simulado = set()
    if com_simulados and sem_revisao >= 2:
        for s in range(primeira_revisao, n_semanas):
            dias_simulado.add(ultimo_dia_semana[s])

    # 1ª passada: decide a matéria de cada bloco pelo método do maior "atraso" em relação à cota
    atribuido = {n: 0 for n in pesos}
    total_atrib = 0
    blocos = []  # (semana, dia, ordem, bloco, minutos, matéria, fase)
    for d in dias:
        semana, dia = (d - inicio_crono).days // 7 + 1, d.weekday()
        fase = "revisao" if semana >= primeira_revisao else "conteudo"
        if d in dias_simulado:
            blocos.append((semana, dia, 1, "Simulado", min(minutos_dia, 300), "Simulados", "simulado"))
            continue
        rev = 30 if minutos_dia >= 120 else 0
        red = 0
        if redacao and d == ultimo_dia_semana[semana] and minutos_dia - rev >= 120:
            red = 90
        conteudo = minutos_dia - rev - red
        if conteudo >= 150:
            a = min(120, int(-(-conteudo * 0.55 // 30) * 30))
            partes = [a, conteudo - a]
        else:
            partes = [conteudo] if conteudo > 0 else []
        ordem, usadas_hoje = 1, set()
        for i, mins in enumerate(partes):
            candidatas = [n for n in pesos if n not in usadas_hoje] or list(pesos)
            if i == 0 and len(partes) > 1:  # o bloco longo do dia vai para uma matéria de prioridade Alta
                altas = [n for n in candidatas if prioridade_de.get(n) == "Alta"]
                candidatas = altas or candidatas
            escolhida = max(candidatas, key=lambda n: (cota[n] * (total_atrib + mins) - atribuido[n], pesos[n]))
            atribuido[escolhida] += mins
            total_atrib += mins
            usadas_hoje.add(escolhida)
            blocos.append((semana, dia, ordem, f"Bloco {i + 1}", mins, escolhida, fase))
            ordem += 1
        if red:
            blocos.append((semana, dia, ordem, "Redação", red, redacao[0], "redacao"))
            ordem += 1
        if rev:
            texto_rev = "Revisão da semana" if d == ultimo_dia_semana[semana] else "Caderno de erros"
            blocos.append((semana, dia, ordem, "Revisão", rev, "Revisão", texto_rev))

    # 2ª passada: coloca os tópicos de cada matéria, em ordem, nas sessões da fase de conteúdo
    sessoes = {}
    for idx, b in enumerate(blocos):
        if b[6] == "conteudo":
            sessoes.setdefault(b[5], []).append(idx)
    rotulos = {}
    for nome, idxs in sessoes.items():
        for idx, rot in zip(idxs, _distribuir_topicos(materias[nome]["topicos"], len(idxs))):
            rotulos[idx] = rot
    itens = []
    for idx, (semana, dia, ordem, bloco, mins, materia, fase) in enumerate(blocos):
        if fase == "conteudo":
            topico = rotulos.get(idx, "Questões e revisão")
        elif fase == "revisao":
            topico = "Revisão geral + questões"
        elif fase == "simulado":
            topico = "Simulado completo + redação"
        elif fase == "redacao":
            topico = "Redação semanal (cronometrada)"
        else:
            topico = fase
        itens.append((semana, dia, ordem, bloco, mins, materia, topico))
    return itens

def salvar_edital(conn, edital, ajustes=None):
    import json
    c = conn.cursor()
    c.execute("SELECT id, ajustes FROM editais WHERE nome = ?", (edital["objetivo"],))
    res = c.fetchone()
    if res:
        c.execute("UPDATE editais SET conteudo = ? WHERE id = ?", (json.dumps(edital, ensure_ascii=False), res[0]))
    else:
        c.execute("INSERT INTO editais (nome, conteudo, ajustes) VALUES (?, ?, ?)",
                  (edital["objetivo"], json.dumps(edital, ensure_ascii=False), json.dumps(ajustes or {}, ensure_ascii=False)))
    conn.commit()

# -----------------------------------------------------------------------------
# NOVO: SIMULADO SÓ COM O QUE JÁ FOI ESTUDADO
# -----------------------------------------------------------------------------
import re as _re
MATERIAS_FORA_DO_SIMULADO = {"Revisão", "Simulados", "Redação"}
TOPICOS_GENERICOS = ("caderno de erros", "revisão da semana", "revisão geral", "revisão leve", "redação semanal",
                     "simulado", "questões e revisão", "só lei seca", "revisão (semana", "redação (semana")

def limpar_nome_topico(nome):
    """Tira o prefixo do cronograma ('S01 Seg 12/10 · ') e marcas como '(parte 2)', '(questões)', 'Lei seca: '."""
    t = str(nome).split(" · ", 1)[-1].strip()
    t = _re.sub(r"\s*\((parte \d+|questões)\)\s*$", "", t, flags=_re.IGNORECASE)
    t = _re.sub(r"^(Lei seca|Continuação):\s*", "", t, flags=_re.IGNORECASE)
    return t.strip()

def assuntos_estudados(conn, meta_id, incluir_parciais=True):
    """Devolve {matéria: [assuntos estudados, sem repetição, na ordem em que foram estudados]}."""
    status = ("Concluído", "Parcial") if incluir_parciais else ("Concluído",)
    marcadores = ",".join("?" * len(status))
    df = pd.read_sql_query(f"""
        SELECT m.nome as materia, t.nome as topico
        FROM topicos t JOIN materias m ON t.materia_id = m.id
        WHERE m.meta_id = ? AND t.status IN ({marcadores})
        ORDER BY COALESCE(t.semana, 0), COALESCE(t.dia, 0), COALESCE(t.ordem, 0), t.id
    """, conn, params=(int(meta_id), *status))
    resultado = {}
    for _, r in df.iterrows():
        if r["materia"] in MATERIAS_FORA_DO_SIMULADO:
            continue
        assunto = limpar_nome_topico(r["topico"])
        if not assunto or any(g in assunto.lower() for g in TOPICOS_GENERICOS):
            continue
        partes = [a.strip() for a in assunto.split(" | ") if a.strip()]
        lista = resultado.setdefault(r["materia"], [])
        for a in partes:
            if a not in lista:
                lista.append(a)
    return {m: l for m, l in resultado.items() if l}

def distribuir_questoes(materias, pesos, total):
    """Reparte o total de questões pelas matérias estudadas, proporcional ao peso; cada matéria recebe ao menos 1."""
    if not materias:
        return {}
    total = max(total, len(materias))
    soma = sum(pesos.get(m, 1.0) for m in materias)
    base = {m: max(1, int(total * pesos.get(m, 1.0) / soma)) for m in materias}
    sobra = total - sum(base.values())
    restos = sorted(materias, key=lambda m: -(total * pesos.get(m, 1.0) / soma - int(total * pesos.get(m, 1.0) / soma)))
    i = 0
    while sobra > 0:
        base[restos[i % len(restos)]] += 1
        sobra -= 1
        i += 1
    while sobra < 0:
        maior = max(base, key=base.get)
        if base[maior] <= 1:
            break
        base[maior] -= 1
        sobra += 1
    return base

# -----------------------------------------------------------------------------
# NOVO: ORIENTAÇÕES DE ESTUDO POR BLOCO (artigos, foco e divisão do tempo)
# -----------------------------------------------------------------------------
def topico_sem_prefixo(nome):
    return str(nome).split(" · ", 1)[-1].strip()

def buscar_orientacao(conn, materia, nome_topico):
    """Procura a orientação do bloco: primeiro pelo tópico exato, depois pelo assunto 'limpo'."""
    c = conn.cursor()
    exato = topico_sem_prefixo(nome_topico)
    c.execute("SELECT texto FROM orientacoes WHERE materia = ? AND topico = ?", (materia, exato))
    res = c.fetchone()
    if res:
        return res[0]
    limpo = limpar_nome_topico(nome_topico)
    c.execute("SELECT topico, texto FROM orientacoes WHERE materia = ?", (materia,))
    for top, txt in c.fetchall():
        if limpar_nome_topico(top) == limpo:
            return txt
    return ""

def salvar_orientacao(conn, materia, topico, texto):
    c = conn.cursor()
    # Guarda como 'usuario': a orientação padrão do app nunca volta por cima da sua
    # (se você apagar o texto, fica vazio e a padrão não reaparece)
    c.execute("INSERT OR REPLACE INTO orientacoes (materia, topico, texto, origem) VALUES (?, ?, ?, 'usuario')",
              (materia, topico_sem_prefixo(topico), texto.strip()))
    conn.commit()

def ler_arquivo_orientacoes(dados):
    """Confere o arquivo de orientações. Retorna (lista de (matéria, tópico, texto), erros)."""
    itens, erros = [], []
    lista = dados.get("orientacoes")
    if not isinstance(lista, list) or not lista:
        return [], ["Falta a lista 'orientacoes'."]
    for n, o in enumerate(lista, start=1):
        try:
            mat, top, txt = str(o["materia"]).strip(), str(o["topico"]).strip(), str(o["texto"]).strip()
        except (KeyError, TypeError):
            erros.append(f"Orientação nº {n}: falta matéria, tópico ou texto.")
            continue
        if not (mat and top and txt):
            erros.append(f"Orientação nº {n}: matéria, tópico ou texto vazio.")
            continue
        itens.append((mat, topico_sem_prefixo(top), txt))
    return (itens, []) if not erros else ([], erros[:10])

def total_semanas(meta_id, conn):
    c = conn.cursor()
    c.execute("""SELECT MAX(t.semana) FROM topicos t JOIN materias m ON t.materia_id = m.id
                 WHERE m.meta_id = ?""", (int(meta_id),))
    res = c.fetchone()[0]
    return int(res) if res else 0

def semana_e_dia_de_hoje(meta_id):
    """Devolve (semana, dia) de hoje no cronograma. dia = 0..6 (5 e 6 = fim de semana)."""
    inicio = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id}", CRONO_INICIO.isoformat()))
    hoje = hoje_local()
    return (hoje - inicio).days // 7 + 1, hoje.weekday()

def meta_tem_cronograma(meta_id, conn):
    c = conn.cursor()
    c.execute("""SELECT COUNT(*) FROM topicos t JOIN materias m ON t.materia_id = m.id
                 WHERE m.meta_id = ? AND t.semana IS NOT NULL""", (int(meta_id),))
    return c.fetchone()[0] > 0

def salvar_status_topico(conn, topico_id, status, minutos=None):
    teoria = 1 if status in ("Parcial", "Concluído") else 0
    resumo = 1 if status == "Concluído" else 0
    c = conn.cursor()
    if minutos is None:
        c.execute("UPDATE topicos SET status = ?, teoria = ?, resumo = MAX(resumo, ?) WHERE id = ?",
                  (status, teoria, resumo, int(topico_id)))
    else:
        antes = c.execute("SELECT COALESCE(minutos_estudados, 0) FROM topicos WHERE id = ?", (int(topico_id),)).fetchone()
        delta = int(minutos) - (int(antes[0]) if antes else 0)
        c.execute("UPDATE topicos SET status = ?, teoria = ?, resumo = MAX(resumo, ?), minutos_estudados = ? WHERE id = ?",
                  (status, teoria, resumo, int(minutos), int(topico_id)))
        if delta != 0:  # guarda QUANDO você estudou (para o calendário e as horas por semana)
            c.execute("INSERT INTO sessoes (data, topico_id, minutos, origem) VALUES (?, ?, ?, 'app')",
                      (hoje_local().isoformat(), int(topico_id), delta))
    conn.commit()

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🛡️ Sistema Unificado de Gestão de Estudos")

# -----------------------------------------------------------------------------
# NOVO: AVISOS DE CONFIRMAÇÃO (não somem quando a tela recarrega)
# -----------------------------------------------------------------------------
def avisar(msg, tipo="success"):
    """Guarda um aviso para mostrar depois do recarregamento da tela.
    Se foi uma gravação bem-sucedida, envia também a cópia para a nuvem e confirma."""
    if tipo in ("success", "info") and nuvem_estado()["ativa"]:
        ok, det = nuvem_enviar()
        msg += " ☁️ Cópia guardada na nuvem." if ok else ""
        if not ok:
            st.session_state.setdefault("_avisos", []).append(
                ("error", f"Salvo no app, mas NÃO na nuvem ({det}). Se o app reiniciar, isto pode se perder. "
                          "Tente salvar de novo e, se repetir, me avise."))
    st.session_state.setdefault("_avisos", []).append((tipo, msg))

def mostrar_avisos():
    for tipo, msg in st.session_state.pop("_avisos", []):
        icone = {"success": "✅", "error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(tipo, "ℹ️")
        getattr(st, tipo)(f"{icone} {msg}")
        try:
            st.toast(msg[:140], icon=icone)
        except Exception:
            pass

def conferir_status(conn, topico_id):
    """Relê do banco o status e os minutos do bloco, para confirmar a gravação."""
    r = conn.execute("SELECT nome, status, COALESCE(minutos_estudados, 0) FROM topicos WHERE id = ?", (int(topico_id),)).fetchone()
    return r

def salvar_status_com_aviso(conn, topico_id, status, minutos=None):
    try:
        salvar_status_topico(conn, topico_id, status, minutos)
        r = conferir_status(conn, topico_id)
        if r and r[1] == status:
            avisar(f"Salvo e conferido: \"{r[0].split(' · ', 1)[-1]}\" está como {r[1]}, com {r[2]} min registrados.")
        else:
            avisar("O app tentou salvar, mas ao conferir o banco o status não mudou. Tente de novo e, se repetir, me avise.", "error")
    except Exception as e:
        avisar(f"NÃO foi salvo. Erro: {e}", "error")

# -----------------------------------------------------------------------------
# NOVO: DIA DE ESCALA – desloca o cronograma inteiro 1 dia útil para frente
# -----------------------------------------------------------------------------
import json as _json_esc

def ler_escalas(meta_id):
    try:
        return _json_esc.loads(get_config(f"escalas_{meta_id}", "[]"))
    except Exception:
        return []

def gravar_escalas(meta_id, lista):
    set_config(f"escalas_{meta_id}", _json_esc.dumps(sorted(set(lista))))

def deslocar_cronograma(conn, meta_id, a_partir_idx, passo):
    """Move em 'passo' dias úteis todos os blocos cujo índice (semana-1)*5+dia seja >= a_partir_idx.
    Sábado e domingo não contam: o bloco de sexta vai para a segunda seguinte."""
    inicio = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id}", CRONO_INICIO.isoformat()))
    linhas = conn.execute("""SELECT t.id, t.nome, t.semana, t.dia FROM topicos t JOIN materias m ON t.materia_id = m.id
                             WHERE m.meta_id = ? AND t.semana IS NOT NULL""", (int(meta_id),)).fetchall()
    movidos = 0
    for tid, nome, sem, dia in linhas:
        idx = (int(sem) - 1) * 5 + int(dia)
        if idx >= a_partir_idx:
            novo = idx + passo
            nsem, ndia = novo // 5 + 1, novo % 5
            conn.execute("UPDATE topicos SET semana = ?, dia = ?, nome = ? WHERE id = ?",
                         (nsem, ndia, nome_topico_crono(nsem, ndia, topico_sem_prefixo(nome), inicio), tid))
            movidos += 1
    conn.commit()
    return movidos

def ultima_data_cronograma(conn, meta_id):
    inicio = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id}", CRONO_INICIO.isoformat()))
    r = conn.execute("""SELECT MAX((t.semana - 1) * 5 + t.dia) FROM topicos t JOIN materias m ON t.materia_id = m.id
                        WHERE m.meta_id = ? AND t.semana IS NOT NULL""", (int(meta_id),)).fetchone()[0]
    return None if r is None else inicio + datetime.timedelta(weeks=r // 5, days=r % 5)

# -----------------------------------------------------------------------------
# NOVO: FIQUEI PARA TRÁS – recomeçar o cronograma a partir de hoje
# O que já foi concluído fica onde está. Tudo o que está pendente (inclusive o que
# ficou para trás) é reorganizado, em ordem, a partir de hoje, SEM passar da data final.
# Para caber: (1) sobras de dias atrasados são juntadas num mesmo dia quando cabem em 4 h;
# (2) se ainda faltar espaço, saem os dias de REVISÃO GERAL mais antigos da reta final
# (nunca conteúdo novo, nunca simulado, nunca a última semana).
# -----------------------------------------------------------------------------
MINUTOS_DIA = 240

def _idx_de_data(inicio, data):
    """Índice do dia útil no cronograma: (semana-1)*5 + dia. Fim de semana vai para a segunda seguinte."""
    while data.weekday() > 4:
        data += datetime.timedelta(days=1)
    return ((data - inicio).days // 7) * 5 + data.weekday()

def _bloco_de_revisao(materia, topico):
    t = topico.lower()
    return materia == REV or t.startswith("revisão") or "revisão geral" in t or "(semana de carnaval)" in t

def planejar_recomeco(conn, meta_id, data_inicio):
    """Calcula o recomeço sem gravar nada. Devolve um dicionário com o plano ou com 'erro'."""
    inicio = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id}", CRONO_INICIO.isoformat()))
    hoje_idx = _idx_de_data(inicio, data_inicio)
    linhas = conn.execute("""SELECT t.id, t.semana, t.dia, t.ordem, m.nome, t.nome, t.status,
                                    COALESCE(t.minutos_planejados, 0), COALESCE(t.minutos_estudados, 0)
                             FROM topicos t JOIN materias m ON t.materia_id = m.id
                             WHERE m.meta_id = ? AND t.semana IS NOT NULL""", (int(meta_id),)).fetchall()
    concluidos = {topico_sem_prefixo(r[5]) for r in linhas if r[6] == "Concluído"}
    vagas = sorted({(r[1] - 1) * 5 + r[2] for r in linhas if (r[1] - 1) * 5 + r[2] >= hoje_idx})
    dias = {}
    for r in linhas:
        if r[6] == "Concluído":
            continue
        tid, sem, dia, ordem, materia, nome, status, prev, feito = r
        topico = topico_sem_prefixo(nome)
        dias.setdefault((sem - 1) * 5 + dia, []).append({
            "id": tid, "ordem": ordem, "materia": materia, "topico": topico,
            "resta": max(prev - feito, 0) if status == "Parcial" else prev,
            # bloco dispensável num dia atrasado: caderno de erros/revisão curtos, ou lei seca já feita em outro bloco
            "dispensavel": (materia == REV and prev <= 30) or (topico.startswith("Lei seca:") and topico in concluidos)})
    unidades = []  # cada unidade = lista de blocos que vão para um mesmo dia
    for idx in sorted(dias):
        blocos = sorted(dias[idx], key=lambda b: b["ordem"])
        unidades.append({"idx": idx, "blocos": blocos, "atrasado": idx < hoje_idx})
    # (1) junta sobras de dias atrasados vizinhos quando cabem num dia
    descartados, juntadas = [], 0
    i = 0
    while i < len(unidades) - 1:
        a, b = unidades[i], unidades[i + 1]
        if a["atrasado"] and b["atrasado"]:
            total = sum(x["resta"] for x in a["blocos"] + b["blocos"])
            essenciais = [x for x in a["blocos"] + b["blocos"] if not x["dispensavel"]]
            if total <= MINUTOS_DIA:
                a["blocos"] += b["blocos"]
            elif sum(x["resta"] for x in essenciais) <= MINUTOS_DIA:
                descartados += [x for x in a["blocos"] + b["blocos"] if x["dispensavel"]]
                a["blocos"] = essenciais
            else:
                i += 1
                continue
            del unidades[i + 1]
            juntadas += 1
        else:
            i += 1
    # (2) corta revisões gerais mais antigas da reta final, se ainda faltar espaço
    excesso = len(unidades) - len(vagas)
    ultima_semana = set(vagas[-5:])
    cortados_dias = []
    if excesso > 0:
        for u in list(unidades):
            if excesso == 0:
                break
            so_revisao = all(_bloco_de_revisao(x["materia"], x["topico"]) and x["materia"] != SIM for x in u["blocos"])
            if not u["atrasado"] and so_revisao and u["idx"] not in ultima_semana:
                unidades.remove(u)
                cortados_dias.append(u)
                excesso -= 1
    if excesso > 0:
        return {"erro": f"Mesmo cortando revisões, faltam {excesso} dia(s) até o fim do cronograma."}
    mover = []
    for u, vaga in zip(unidades, vagas):
        for ordem, x in enumerate(u["blocos"], start=1):
            mover.append((x["id"], vaga // 5 + 1, vaga % 5, ordem, x["topico"]))
    return {"inicio": inicio, "mover": mover, "descartados": descartados, "cortados_dias": cortados_dias,
            "juntadas": juntadas, "vagas": len(vagas),
            "atrasados": sum(1 for u in unidades if u["atrasado"]) + juntadas}

def aplicar_recomeco(conn, meta_id, data_inicio):
    plano = planejar_recomeco(conn, meta_id, data_inicio)
    if "erro" in plano:
        return plano
    inicio = plano["inicio"]
    for tid, sem, dia, ordem, topico in plano["mover"]:
        conn.execute("UPDATE topicos SET semana = ?, dia = ?, ordem = ?, nome = ? WHERE id = ?",
                     (sem, dia, ordem, nome_topico_crono(sem, dia, topico, inicio), tid))
    apagar = [x["id"] for x in plano["descartados"]] + [x["id"] for u in plano["cortados_dias"] for x in u["blocos"]]
    for tid in apagar:  # só blocos pendentes, sem questões nem minutos registrados
        tem_registro = conn.execute("SELECT 1 FROM exercicios WHERE topico_id = ? UNION SELECT 1 FROM sessoes WHERE topico_id = ?",
                                    (tid, tid)).fetchone()
        if not tem_registro:
            conn.execute("DELETE FROM topicos WHERE id = ? AND status = 'Pendente' AND COALESCE(minutos_estudados, 0) = 0", (tid,))
    conn.commit()
    resumo = []
    for u in plano["cortados_dias"]:
        d = inicio + datetime.timedelta(weeks=u["idx"] // 5, days=u["idx"] % 5)
        resumo.append(f"{d:%d/%m}: " + " + ".join(f'{x["materia"]} ({x["topico"]})' for x in u["blocos"]))
    plano["resumo_cortes"] = resumo
    return plano

def recomeco_automatico_20_10(conn):
    """Pedido em 20/10/2026: recomeçar o cronograma CFO a partir de 20/10. Roda uma vez só."""
    chave = "recomeco_2026_10_20"
    est = nuvem_estado()
    if get_config(chave, "") or (est["ativa"] and est["status"] != "ok"):
        return  # sem ler a nuvem, não mexe (para não trabalhar sobre dados velhos)
    meta = conn.execute("SELECT id FROM metas WHERE nome = ?", (CRONO_META_NOME,)).fetchone()
    if not meta:
        return
    data = max(hoje_local(), datetime.date(2026, 10, 20))
    plano = aplicar_recomeco(conn, meta[0], data)
    if "erro" in plano:
        set_config(chave, "erro: " + plano["erro"])
        return
    set_config(chave, f"feito em {data:%d/%m/%Y}")
    avisar(f"🔁 Cronograma recomeçado a partir de {data:%d/%m}: o que estava pendente foi reorganizado até 26/02. "
           f"Dias de revisão geral retirados para caber: {'; '.join(plano['resumo_cortes']) or 'nenhum'}.", "info")


menu = st.sidebar.radio("Navegação", [
    "📅 Meta & Rotina do Dia",
    "🧭 Planejar Estudos",
    "🗓️ Cronograma Semanal",
    "🎯 Simulado do que já estudei",
    "📝 Registrar Questões", 
    "✍️ Redações",
    "📊 Dashboard de Evolução", 
    "⚙️ Gerenciador"
])
mostrar_avisos()
_ne = nuvem_estado()
if _ne["status"] == "erro":
    st.error("☁️ O app NÃO conseguiu ler seus dados da nuvem ao abrir. Para não perder nada, ele NÃO vai gravar "
             f"na nuvem agora. Toque em \"Tentar de novo\" em 1 minuto; se continuar, me avise. Detalhe: {_ne['erro'][:150]}")
    if st.button("🔄 Tentar ler a nuvem de novo"):
        nuvem_estado.clear()
        _ne2 = nuvem_estado()
        avisar({"ok": "Nuvem lida com sucesso: seus dados foram carregados.",
                "vazia": "Nuvem conectada (ainda sem cópias guardadas)."}.get(_ne2["status"], "") if _ne2["status"] in ("ok", "vazia")
               else "Ainda não foi possível ler a nuvem.", "info" if _ne2["status"] in ("ok", "vazia") else "error")
        st.rerun()
elif not _ne["ativa"]:
    st.warning("☁️ A guarda na nuvem ainda não está configurada: seus dados podem sumir quando o app reiniciar. "
               "Baixe o backup em ⚙️ Gerenciador → 📅 Cronogramas.")


def ajuste_estatuto_14_10(conn):
    """Ajuste pedido em 14/10/2026: o Estatuto (Lei 6.783), prioridade do edital, passa para hoje.
    Troca os blocos 1 e 3 de segunda (12/10) com os de quarta (14/10) da semana 1. Roda uma vez só,
    apenas em 14/10, e só se os quatro blocos ainda estiverem pendentes (nada do seu progresso se perde)."""
    chave = "ajuste_estatuto_2026_10_14"
    if get_config(chave, "") or hoje_local() != datetime.date(2026, 10, 14):
        return
    c = conn.cursor()
    c.execute("SELECT id FROM metas WHERE nome = ?", (CRONO_META_NOME,))
    meta = c.fetchone()
    if not meta:
        return
    inicio = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta[0]}", CRONO_INICIO.isoformat()))
    if inicio != CRONO_INICIO:
        return
    blocos = {}
    for dia, ordem in ((0, 1), (0, 3), (2, 1), (2, 3)):
        c.execute("""SELECT t.id, t.nome, t.status, COALESCE(t.minutos_estudados, 0) FROM topicos t
                     JOIN materias m ON t.materia_id = m.id
                     WHERE m.meta_id = ? AND t.semana = 1 AND t.dia = ? AND t.ordem = ?""", (meta[0], dia, ordem))
        r = c.fetchone()
        if not r or r[2] != "Pendente" or r[3] > 0:
            set_config(chave, "pulado")
            return
        blocos[(dia, ordem)] = r
    if "Estatuto" not in blocos[(0, 1)][1]:
        set_config(chave, "pulado")
        return
    for ordem in (1, 3):
        seg, qua = blocos[(0, ordem)], blocos[(2, ordem)]
        for tid, nome, novo_dia in ((seg[0], seg[1], 2), (qua[0], qua[1], 0)):
            c.execute("UPDATE topicos SET dia = ?, nome = ? WHERE id = ?",
                      (novo_dia, nome_topico_crono(1, novo_dia, topico_sem_prefixo(nome), inicio), tid))
    conn.commit()
    set_config(chave, "feito")

def preencher_sessoes_antigas(conn):
    """Uma vez só: minutos registrados antes da tabela de sessões viram sessões na data do bloco (estimativa)."""
    if get_config("sessoes_preenchidas", ""):
        return
    linhas = conn.execute("""SELECT t.id, t.semana, t.dia, t.minutos_estudados, m.meta_id FROM topicos t
                             JOIN materias m ON t.materia_id = m.id
                             WHERE COALESCE(t.minutos_estudados, 0) > 0 AND t.semana IS NOT NULL
                               AND t.id NOT IN (SELECT topico_id FROM sessoes)""").fetchall()
    for tid, sem, dia, mins, meta_id in linhas:
        inicio = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id}", CRONO_INICIO.isoformat()))
        data = min(inicio + datetime.timedelta(weeks=int(sem) - 1, days=int(dia)), hoje_local())
        conn.execute("INSERT INTO sessoes (data, topico_id, minutos, origem) VALUES (?, ?, ?, 'estimado')",
                     (data.isoformat(), tid, int(mins)))
    conn.commit()
    set_config("sessoes_preenchidas", "sim")

conn = get_db()
preencher_sessoes_antigas(conn)
if nuvem_estado()['status'] == 'vazia':
    nuvem_enviar()
ajuste_estatuto_14_10(conn)
recomeco_automatico_20_10(conn)

# =============================================================================
# MENU 1: META & ROTINA DO DIA
# =============================================================================
if menu == "📅 Meta & Rotina do Dia":
    st.header("🎯 Sugestão Diária de Estudo e Rotina Policial")
    
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.warning("Nenhum objetivo cadastrado. Carregue o cronograma em ⚙️ Gerenciador → 📅 Cronogramas.")
    else:
        meta_sel_rotina = st.selectbox("Selecione o Objetivo do Dia:", df_metas['nome'].tolist())
        meta_id_rotina = df_metas[df_metas['nome'] == meta_sel_rotina]['id'].values[0]

        # NOVO: se o objetivo tem cronograma, mostra os blocos de hoje
        if meta_tem_cronograma(meta_id_rotina, conn):
            semana_hoje, dia_hoje = semana_e_dia_de_hoje(meta_id_rotina)
            n_semanas = total_semanas(meta_id_rotina, conn)
            inicio_rot = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id_rotina}", CRONO_INICIO.isoformat()))
            if semana_hoje < 1:
                st.info(f"📆 O cronograma começa na segunda-feira, {inicio_rot:%d/%m/%Y}.")
            elif semana_hoje > n_semanas:
                st.success(f"🏁 O cronograma de {n_semanas} semanas terminou. Boa prova!")
            elif dia_hoje > 4:
                st.info(f"📆 Hoje é fim de semana (semana {semana_hoje}). Use o tempo livre para repor o que ficou pendente:")
                df_pend = pd.read_sql_query("""
                    SELECT t.nome as Tópico, m.nome as Matéria, t.status as Status
                    FROM topicos t JOIN materias m ON t.materia_id = m.id
                    WHERE m.meta_id = ? AND t.semana = ? AND t.status != 'Concluído'
                    ORDER BY t.dia, t.ordem
                """, conn, params=(int(meta_id_rotina), int(semana_hoje)))
                if df_pend.empty:
                    st.success("🎉 Nada pendente nesta semana!")
                else:
                    st.dataframe(df_pend, use_container_width=True, hide_index=True)
            else:
                idx_hoje = (semana_hoje - 1) * 5 + dia_hoje
                hoje_iso = hoje_local().isoformat()
                escalas = ler_escalas(meta_id_rotina)
                if hoje_iso in escalas:
                    st.warning("🚨 **Hoje está marcado como dia de escala.** Todo o cronograma foi adiado 1 dia útil: "
                               "o que era de hoje passou para amanhã, o de amanhã para depois, e assim por diante.")
                    if st.button("↩️ Desfazer: não estou mais escalado hoje", key="esc_desfazer"):
                        try:
                            n = deslocar_cronograma(conn, meta_id_rotina, idx_hoje + 1, -1)
                            gravar_escalas(meta_id_rotina, [d for d in escalas if d != hoje_iso])
                            fim = ultima_data_cronograma(conn, meta_id_rotina)
                            avisar(f"Escala desfeita: {n} blocos voltaram 1 dia e os blocos de hoje estão de volta. "
                                   f"O cronograma agora termina em {fim:%d/%m/%Y}.")
                        except Exception as e:
                            avisar(f"NÃO foi desfeito. Erro: {e}", "error")
                        st.rerun()
                else:
                    with st.expander("🚨 Estou escalado hoje (adiar o cronograma 1 dia)"):
                        st.write("Todo o cronograma anda 1 dia útil para frente, a partir de hoje: o que era de hoje vai "
                                 "para amanhã, o de amanhã para depois de amanhã, e assim por diante. Nada é apagado. "
                                 "Sexta-feira passa para a segunda seguinte. O que você já estudou em dias anteriores não muda.")
                        confirma = st.checkbox("Confirmo que estou escalado hoje", key="esc_conf")
                        if st.button("Adiar o cronograma 1 dia", disabled=not confirma, key="esc_btn"):
                            try:
                                n = deslocar_cronograma(conn, meta_id_rotina, idx_hoje, 1)
                                gravar_escalas(meta_id_rotina, escalas + [hoje_iso])
                                restam = conn.execute("""SELECT COUNT(*) FROM topicos t JOIN materias m ON t.materia_id = m.id
                                    WHERE m.meta_id = ? AND (t.semana - 1) * 5 + t.dia = ?""", (int(meta_id_rotina), idx_hoje)).fetchone()[0]
                                fim = ultima_data_cronograma(conn, meta_id_rotina)
                                if restam == 0:
                                    msg = (f"Cronograma adiado 1 dia e conferido: {n} blocos foram para frente. "
                                           f"O último bloco agora é em {fim:%d/%m/%Y}.")
                                    if meta_sel_rotina == CRONO_META_NOME and fim >= datetime.date(2027, 2, 27):
                                        msg += " Atenção: o fim do cronograma encostou na prova (28/02/2027). Me peça para reorganizar as semanas finais."
                                    avisar(msg)
                                else:
                                    avisar("O app tentou adiar, mas ainda há blocos hoje. Tente de novo.", "error")
                            except Exception as e:
                                avisar(f"NÃO foi adiado. Erro: {e}", "error")
                            st.rerun()
                st.subheader(f"📆 Semana {semana_hoje} · {DIAS_SEMANA[dia_hoje]} – blocos de hoje")
                df_hoje = pd.read_sql_query("""
                    SELECT t.id, t.nome, t.bloco, t.minutos_planejados, t.minutos_estudados, t.status, m.nome as materia
                    FROM topicos t JOIN materias m ON t.materia_id = m.id
                    WHERE m.meta_id = ? AND t.semana = ? AND t.dia = ?
                    ORDER BY t.ordem
                """, conn, params=(int(meta_id_rotina), int(semana_hoje), int(dia_hoje)))
                if df_hoje.empty:
                    st.info("Nenhum bloco previsto para hoje." if hoje_iso not in escalas else
                            "Hoje é dia de escala: sem blocos. Bom serviço!")
                for _, row in df_hoje.iterrows():
                    topico_id = int(row['id'])
                    minutos_plan = int(row['minutos_planejados'] or 0)
                    icone = "✅" if row['status'] == "Concluído" else ("⏳" if row['status'] == "Parcial" else "📖")
                    with st.expander(f"{icone} **{row['bloco']} · {row['materia']}** | {minutos_plan} min", expanded=row['status'] != "Concluído"):
                        st.markdown(f"**Conteúdo:** {row['nome'].split(' · ', 1)[-1]}")
                        orientacao = buscar_orientacao(conn, row['materia'], row['nome'])
                        if orientacao:
                            st.info("📌 **Orientação**\n\n" + orientacao)
                        if st.toggle("✏️ Escrever ou editar a orientação", key=f"ori_tg_{topico_id}"):
                            novo_txt = st.text_area("Orientação", value=orientacao, height=150,
                                                    key=f"ori_{topico_id}", label_visibility="collapsed")
                            if st.button("💾 Salvar orientação", key=f"ori_salvar_{topico_id}"):
                                try:
                                    salvar_orientacao(conn, row['materia'], row['nome'], novo_txt)
                                    avisar("Orientação salva e conferida." if buscar_orientacao(conn, row['materia'], row['nome']) == novo_txt.strip()
                                           else "Orientação apagada." if not novo_txt.strip() else "A orientação não foi confirmada no banco. Tente de novo.",
                                           "success" if buscar_orientacao(conn, row['materia'], row['nome']) == novo_txt.strip() or not novo_txt.strip() else "error")
                                except Exception as e:
                                    avisar(f"Orientação NÃO salva. Erro: {e}", "error")
                                st.rerun()
                        st.write(f"**Status:** `{row['status']}` · **Minutos registrados:** {int(row['minutos_estudados'] or 0)}")

                        timer_data = get_timer_state(topico_id, minutos_plan * 60)
                        seg_restantes = timer_data['restante']
                        if timer_data['status'] == 'FINISHED':
                            st.success("🔔 Tempo do bloco concluído!")
                        st.markdown(f"### ⏳ `{seg_restantes // 3600:02d}:{(seg_restantes % 3600) // 60:02d}:{seg_restantes % 60:02d}`")
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if st.button("▶️ Iniciar / Continuar", key=f"cr_start_{topico_id}"):
                                set_timer_start(topico_id, seg_restantes)
                                st.rerun()
                        with c2:
                            if st.button("⏸️ Pausar", key=f"cr_pause_{topico_id}"):
                                set_timer_pause(topico_id, seg_restantes)
                                st.rerun()
                        with c3:
                            if st.button("🔄 Zerar", key=f"cr_reset_{topico_id}"):
                                set_timer_stop(topico_id)
                                st.rerun()

                        # minutos já cronometrados neste bloco
                        minutos_cronometrados = max(0, round((minutos_plan * 60 - seg_restantes) / 60)) if timer_data['status'] != 'STOPPED' else 0

                        minutos_ja = int(row['minutos_estudados'] or 0)
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("✅ Concluí este bloco", key=f"cr_conc_{topico_id}"):
                                if minutos_cronometrados > 0:
                                    minutos = minutos_ja + minutos_cronometrados
                                else:
                                    minutos = minutos_ja if minutos_ja > 0 else minutos_plan
                                salvar_status_com_aviso(conn, topico_id, "Concluído", minutos)
                                set_timer_stop(topico_id)
                                st.rerun()
                        with col_b:
                            if st.button("⏳ Fiz só uma parte", key=f"cr_parc_{topico_id}"):
                                salvar_status_com_aviso(conn, topico_id, "Parcial", minutos_ja + minutos_cronometrados)
                                set_timer_stop(topico_id)
                                st.rerun()

                        if timer_data['status'] == 'RODANDO':
                            time.sleep(1)
                            st.rerun()
            conn.close()
            st.stop()

        st.info("Este objetivo ainda não tem cronograma. Gere em 🧭 Planejar Estudos ou importe em ⚙️ Gerenciador → 📅 Cronogramas.")

# =============================================================================
# MENU 2: CHECKLIST & ACOMPANHAMENTO
# =============================================================================
elif menu == "🧭 Planejar Estudos":
    import json as _json
    st.header("🧭 Planejar Estudos")
    st.write("Marque o quanto você já sabe de cada matéria e a prioridade dela. "
             "O app distribui as horas até a véspera da prova e monta o cronograma.")
    df_ed = pd.read_sql_query("SELECT id, nome, conteudo, ajustes FROM editais ORDER BY id DESC", conn)
    if df_ed.empty:
        st.info("Nenhum edital salvo ainda. Peça ao Claude o arquivo do edital e envie em "
                "'⚙️ Gerenciador' → aba '📅 Cronogramas' → '📤 Importar'.")
    else:
        nome_ed = st.selectbox("Edital:", df_ed["nome"].tolist())
        linha_ed = df_ed[df_ed["nome"] == nome_ed].iloc[0]
        edital = _json.loads(linha_ed["conteudo"])
        ajustes = _json.loads(linha_ed["ajustes"] or "{}")
        data_prova_ed = datetime.date.fromisoformat(edital["data_prova"])
        cfg = ajustes.get("_config", {})
        
        st.subheader("1. Sua rotina")
        r1, r2 = st.columns(2)
        hoje = hoje_local()
        proxima_segunda = hoje + datetime.timedelta(days=(7 - hoje.weekday()) % 7)
        with r1:
            inicio_escolhido = st.date_input("Começar a estudar em:", value=datetime.date.fromisoformat(cfg.get("inicio", proxima_segunda.isoformat())),
                                             format="DD/MM/YYYY")
            horas_plan = st.number_input("Horas de estudo por dia (segunda a sexta):", min_value=1.0, max_value=10.0,
                                         value=float(cfg.get("horas", get_config("horas_estudo_dia", "4.0"))), step=0.5)
        with r2:
            pct_rev = st.slider("Semanas finais só de revisão (% do período):", 0, 30, int(cfg.get("pct_revisao", 15)), step=5)
            com_sim = st.checkbox("Incluir simulados nas semanas de revisão", value=bool(cfg.get("simulados", True)))
        st.caption(f"Prova em {data_prova_ed:%d/%m/%Y}. O cronograma vai até a véspera.")
        
        st.subheader("2. Suas matérias")
        st.caption("Conhecimento: 0 = não sei nada · 1 = muito pouco · 2 = pouco · 3 = razoável · 4 = bom · "
                   "5 = bom conhecimento e facilidade de aprender")
        with st.form("form_planejar"):
            novos = {}
            for i, m in enumerate(edital["materias"]):
                aj = ajustes.get(m["nome"], {})
                info = f"{m['pontos']:g} pts" + (f" · {m['bloco']}" if m.get("bloco") else "")
                if m.get("tipo") == "redacao":
                    st.markdown(f"**{m['nome']}** · {info}  \n<small>1 redação por semana, sempre no último dia útil.</small>",
                                unsafe_allow_html=True)
                    st.divider()
                    continue
                st.markdown(f"**{m['nome']}** · {info}")
                c_conh, c_prio = st.columns([3, 1])
                with c_conh:
                    conh = st.radio("Conhecimento", [0, 1, 2, 3, 4, 5], horizontal=True,
                                    index=int(aj.get("conhecimento", m.get("conhecimento", 3))),
                                    key=f"conh_{linha_ed['id']}_{i}", label_visibility="collapsed")
                with c_prio:
                    opcoes_prio = ["Alta", "Média", "Baixa"]
                    prio = st.selectbox("Prioridade", opcoes_prio,
                                        index=opcoes_prio.index(aj.get("prioridade", m["prioridade"])),
                                        key=f"prio_{linha_ed['id']}_{i}", label_visibility="collapsed")
                novos[m["nome"]] = {"conhecimento": int(conh), "prioridade": prio}
                st.divider()
            calcular = st.form_submit_button("📊 Calcular distribuição do tempo", type="primary")
        if calcular:
            novos["_config"] = {"inicio": inicio_escolhido.isoformat(), "horas": horas_plan,
                                "pct_revisao": pct_rev, "simulados": com_sim}
            conn.execute("UPDATE editais SET ajustes = ? WHERE id = ?",
                         (_json.dumps(novos, ensure_ascii=False), int(linha_ed["id"])))
            conn.commit()
            ajustes = novos
            st.session_state[f"calculado_{linha_ed['id']}"] = True
        
        with st.expander("Como o app calcula o tempo"):
            st.markdown("Peso de cada matéria = **pontos no edital × prioridade × conhecimento**.\n\n"
                        "- Prioridade: Alta ×1,5 · Média ×1,0 · Baixa ×0,65\n"
                        "- Conhecimento: 0 ×1,6 · 1 ×1,45 · 2 ×1,3 · 3 ×1,15 · 4 ×1,0 · 5 ×0,85\n\n"
                        "Todo dia tem 30 min de revisão (caderno de erros). A redação ocupa 90 min no último dia útil "
                        "de cada semana. As horas restantes são repartidas pelo peso, alternando as matérias. "
                        "Os tópicos de prioridade Alta recebem mais sessões.")
        
        if st.session_state.get(f"calculado_{linha_ed['id']}") or any(k != "_config" for k in ajustes):
            inicio_seg = inicio_escolhido - datetime.timedelta(days=inicio_escolhido.weekday())
            itens_plan = gerar_cronograma_do_edital(edital, ajustes, inicio_seg, horas_plan, pct_rev / 100, com_sim,
                                                    primeiro_dia=inicio_escolhido)
            if not itens_plan:
                st.error("Não há dias úteis entre a data de início e a prova. Ajuste a data de início.")
            else:
                st.subheader("3. Distribuição calculada")
                df_pl = pd.DataFrame(itens_plan, columns=["Semana", "Dia", "Ordem", "Bloco", "Minutos", "Matéria", "Tópico"])
                tot_h = df_pl["Minutos"].sum() / 60
                k1, k2, k3 = st.columns(3)
                k1.metric("Semanas", int(df_pl["Semana"].max()))
                k2.metric("Horas no total", f"{tot_h:.0f} h")
                k3.metric("Blocos", len(df_pl))
                por_mat = (df_pl.groupby("Matéria")["Minutos"].sum() / 60).round(1).sort_values(ascending=False).reset_index()
                por_mat.columns = ["Matéria", "Horas"]
                por_mat["Parte do tempo"] = por_mat["Horas"] / tot_h
                st.dataframe(por_mat, column_config={
                    "Horas": st.column_config.NumberColumn("Horas", format="%.1f"),
                    "Parte do tempo": st.column_config.ProgressColumn("Parte do tempo", min_value=0.0, max_value=float(por_mat["Parte do tempo"].max()))
                }, use_container_width=True, hide_index=True)
                with st.expander("Ver a semana 1"):
                    df_v = df_pl[df_pl["Semana"] == 1].copy()
                    df_v["Dia"] = df_v["Dia"].apply(lambda d: DIAS_SEMANA[int(d)])
                    st.dataframe(df_v[["Dia", "Bloco", "Minutos", "Matéria", "Tópico"]], use_container_width=True, hide_index=True)
                
                st.subheader("4. Gerar o cronograma")
                c = conn.cursor()
                c.execute("SELECT id FROM metas WHERE nome = ?", (edital["objetivo"],))
                existe_meta = c.fetchone() is not None
                liberado = True
                if existe_meta:
                    st.warning(f"Já existe um cronograma '{edital['objetivo']}'. Gerar de novo APAGA o progresso "
                               "e as questões registradas nele. Baixe um backup antes, se quiser guardar.")
                    liberado = st.checkbox("Entendi. Quero substituir pelo novo cronograma.", key=f"subst_plan_{linha_ed['id']}")
                if st.button("🚀 Gerar e salvar cronograma", type="primary", disabled=not liberado):
                    n = carregar_cronograma(conn, edital["objetivo"], inicio_seg, itens_plan, edital.get("tipo", "Concurso"),
                                            substituir=existe_meta)
                    set_config("horas_estudo_dia", horas_plan)
                    st.success(f"Cronograma gerado: {n} blocos. Veja em '🗓️ Cronograma Semanal' e em '📅 Meta & Rotina do Dia'.")
                    st.balloons()
        else:
            st.info("Marque suas matérias e toque em **📊 Calcular distribuição do tempo**.")

elif menu == "🗓️ Cronograma Semanal":
    st.header("🗓️ Cronograma Semanal")

    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    metas_crono = [r for _, r in df_metas.iterrows() if meta_tem_cronograma(r['id'], conn)]

    if not metas_crono:
        st.info("Nenhum cronograma carregado ainda. Vá em '⚙️ Gerenciador' → aba '📅 Cronogramas' e carregue ou importe um cronograma.")
    else:
        nomes_crono = [r['nome'] for r in metas_crono]
        meta_sel_cr = st.selectbox("Objetivo:", nomes_crono)
        meta_id_cr = int([r['id'] for r in metas_crono if r['nome'] == meta_sel_cr][0])

        semana_hoje, _ = semana_e_dia_de_hoje(meta_id_cr)
        n_semanas_cr = max(total_semanas(meta_id_cr, conn), 1)
        semana_padrao = min(max(semana_hoje, 1), n_semanas_cr)
        inicio_cr = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id_cr}", CRONO_INICIO.isoformat()))

        with st.expander("🔁 Fiquei para trás: recomeçar o cronograma a partir de hoje"):
            st.write("O que você já concluiu fica onde está. Tudo o que está pendente (inclusive o atrasado) é "
                     "reorganizado em ordem a partir de hoje, **sem passar da data final**. Para caber, sobras de dias "
                     "atrasados são juntadas (até 4 h por dia) e, se ainda faltar espaço, saem os dias de **revisão geral** "
                     "mais antigos da reta final. Conteúdo novo, simulados e a última semana nunca são cortados.")
            plano_prev = planejar_recomeco(conn, meta_id_cr, hoje_local())
            if "erro" in plano_prev:
                st.error(plano_prev["erro"])
            else:
                st.caption(f"Prévia: {plano_prev['juntadas']} junção(ões) de dias atrasados · "
                           f"{len(plano_prev['cortados_dias'])} dia(s) de revisão geral retirados.")
                if st.checkbox("Confirmo que quero recomeçar a partir de hoje", key="recomeco_conf"):
                    if st.button("🔁 Recomeçar agora", key="recomeco_btn"):
                        try:
                            r = aplicar_recomeco(conn, meta_id_cr, hoje_local())
                            avisar("Cronograma recomeçado a partir de hoje. Retirados para caber: "
                                   + ("; ".join(r.get("resumo_cortes", [])) or "nada") + ".")
                        except Exception as e:
                            avisar(f"NÃO foi recomeçado. Erro: {e}", "error")
                        st.rerun()

        def rotulo_semana(s):
            ini = inicio_cr + datetime.timedelta(weeks=s - 1)
            fim = ini + datetime.timedelta(days=4)
            return f"Semana {s} ({ini:%d/%m} a {fim:%d/%m})" + ("  ← atual" if s == semana_hoje else "")

        semana_sel = st.selectbox("Semana:", list(range(1, n_semanas_cr + 1)), index=semana_padrao - 1, format_func=rotulo_semana)

        df_sem = pd.read_sql_query("""
            SELECT t.id, t.dia, t.ordem, t.bloco as Bloco, m.nome as Matéria, t.nome as Tópico,
                   t.minutos_planejados as Previsto_min, t.minutos_estudados as Estudado_min, t.status as Status
            FROM topicos t JOIN materias m ON t.materia_id = m.id
            WHERE m.meta_id = ? AND t.semana = ?
            ORDER BY t.dia, t.ordem
        """, conn, params=(meta_id_cr, int(semana_sel)))

        if df_sem.empty:
            st.info("Nenhum bloco nesta semana.")
        else:
            previsto = int(df_sem['Previsto_min'].fillna(0).sum())
            estudado = int(df_sem['Estudado_min'].fillna(0).sum())
            concluidos = int((df_sem['Status'] == 'Concluído').sum())
            k1, k2, k3 = st.columns(3)
            k1.metric("Blocos concluídos", f"{concluidos}/{len(df_sem)}")
            k2.metric("Horas estudadas", f"{estudado / 60:.1f} h", f"de {previsto / 60:.1f} h previstas", delta_color="off")
            k3.progress(min(1.0, concluidos / len(df_sem)))

            df_sem['Dia'] = df_sem['dia'].apply(lambda d: DIAS_SEMANA[int(d)])
            df_sem['Tópico'] = df_sem['Tópico'].apply(lambda n: n.split(' · ', 1)[-1])
            df_sem['Estudado_min'] = df_sem['Estudado_min'].fillna(0).astype(int)

            st.caption("Altere o Status e os minutos estudados direto na tabela e clique em Salvar.")
            editado = st.data_editor(
                df_sem[['id', 'Dia', 'Bloco', 'Matéria', 'Tópico', 'Previsto_min', 'Estudado_min', 'Status']],
                column_config={
                    "id": None,
                    "Previsto_min": st.column_config.NumberColumn("Previsto (min)"),
                    "Estudado_min": st.column_config.NumberColumn("Estudado (min)", min_value=0, max_value=600, step=5),
                    "Status": st.column_config.SelectboxColumn("Status", options=["Pendente", "Parcial", "Concluído"], required=True)
                },
                disabled=["Dia", "Bloco", "Matéria", "Tópico", "Previsto_min"],
                hide_index=True,
                use_container_width=True,
                key=f"editor_semana_{meta_id_cr}_{semana_sel}"
            )

            if st.button("💾 Salvar a semana"):
                for _, row in editado.iterrows():
                    salvar_status_topico(conn, row['id'], row['Status'], int(row['Estudado_min'] or 0))
                avisar("Semana salva! O Dashboard já foi atualizado.", "success")
                st.rerun()
            
            st.markdown("---")
            st.subheader("📌 Pedir orientações desta semana ao Claude")
            df_ped = pd.read_sql_query("""
                SELECT m.nome as materia, t.nome as topico, t.dia, t.bloco, t.minutos_planejados
                FROM topicos t JOIN materias m ON t.materia_id = m.id
                WHERE m.meta_id = ? AND t.semana = ? ORDER BY t.dia, t.ordem
            """, conn, params=(meta_id_cr, int(semana_sel)))
            vistos, linhas_ped, ja_tem = set(), [], 0
            for _, r in df_ped.iterrows():
                chave = (r["materia"], topico_sem_prefixo(r["topico"]))
                if chave in vistos:
                    continue
                vistos.add(chave)
                if buscar_orientacao(conn, r["materia"], r["topico"]):
                    ja_tem += 1
                    continue
                linhas_ped.append(f'- {DIAS_SEMANA[int(r["dia"])]} · {r["bloco"]} ({int(r["minutos_planejados"] or 0)} min) · '
                                  f'materia: "{chave[0]}" · topico: "{chave[1]}"')
            if not linhas_ped:
                st.success("Todos os blocos desta semana já têm orientação.")
            else:
                st.caption(f"{len(linhas_ped)} blocos sem orientação ({ja_tem} já têm). Copie o pedido e cole na conversa com o Claude.")
                pedido_or = "\n".join([
                    f"PEDIDO DE ORIENTAÇÕES – {meta_sel_cr} – semana {semana_sel}",
                    "",
                    "Claude, prepare as orientações de estudo destes blocos (quais artigos ou itens estudar, o que priorizar "
                    "e como dividir o tempo do bloco), conferindo os artigos no texto atualizado da lei. Devolva um arquivo "
                    ".json no formato de orientações do meu app, usando exatamente a matéria e o tópico abaixo:",
                    "",
                    *linhas_ped])
                st.code(pedido_or, language=None)

# =============================================================================
# MENU 3: REGISTRAR QUESTÕES
# =============================================================================
elif menu == "🎯 Simulado do que já estudei":
    import json as _json
    st.header("🎯 Simulado do que já estudei")
    st.write("O app junta os assuntos que você marcou como estudados e monta um pedido de simulado. "
             "Copie o pedido e cole na conversa com o Claude: ele cria o simulado só com esses assuntos.")
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    if df_metas.empty:
        st.info("Nenhum objetivo cadastrado ainda.")
    else:
        meta_sim = st.selectbox("Objetivo:", df_metas["nome"].tolist())
        meta_sim_id = int(df_metas[df_metas["nome"] == meta_sim]["id"].values[0])
        
        # pesos e banca vindos do edital salvo (se houver)
        pesos_ed, banca, materias_edital = {}, "", []
        c = conn.cursor()
        c.execute("SELECT conteudo FROM editais WHERE nome = ?", (meta_sim,))
        res_ed = c.fetchone()
        if res_ed:
            ed = _json.loads(res_ed[0])
            banca = ed.get("banca", "")
            for m in ed.get("materias", []):
                if m.get("tipo") != "redacao":
                    pesos_ed[m["nome"]] = float(m.get("pontos", 1))
                    materias_edital.append(m["nome"])
        elif meta_sim == CRONO_META_NOME:
            banca = "Instituto AOCP"
            pesos_ed = {LEG: 10, CF: 8, ADM: 7, DPM: 5, PORT: 5, "Estatística": 5, "Informática": 5,
                        "Língua Estrangeira": 5, "Matemática": 5, "Física": 5, "Química": 5, "Biologia": 5}
            materias_edital = list(pesos_ed)
        
        o1, o2 = st.columns(2)
        with o1:
            n_questoes = st.number_input("Quantas questões?", min_value=5, max_value=100, value=40, step=5)
            incluir_parc = st.checkbox("Incluir assuntos marcados como 'Parcial'", value=True)
        with o2:
            banca_txt = st.text_input("Estilo da banca:", value=banca or "Instituto AOCP")
            modo = st.radio("Distribuir as questões:", ["Pelo peso no edital", "Igual entre as matérias"],
                            horizontal=False, index=0 if pesos_ed else 1)
        
        estudados = assuntos_estudados(conn, meta_sim_id, incluir_parc)
        if not estudados:
            st.warning("Nenhum assunto marcado como estudado ainda. Marque os blocos como 'Concluído' "
                       "em '📅 Meta & Rotina do Dia' ou '🗓️ Cronograma Semanal'.")
        else:
            todas = materias_edital or list(estudados)
            escolhidas = st.multiselect("Matérias que entram no simulado:", list(estudados), default=list(estudados))
            pesos_uso = pesos_ed if (modo == "Pelo peso no edital" and pesos_ed) else {}
            dist = distribuir_questoes(escolhidas, pesos_uso, int(n_questoes))
            
            st.subheader("O que entra no simulado")
            linhas = []
            for m in escolhidas:
                linhas.append({"Matéria": m, "Questões": dist.get(m, 0), "Assuntos estudados": len(estudados[m])})
            st.dataframe(pd.DataFrame(linhas), use_container_width=True, hide_index=True)
            faltando = [m for m in todas if m not in estudados]
            if faltando:
                st.caption("Ainda sem nenhum assunto estudado (ficam de fora): " + ", ".join(faltando))
            
            # monta o pedido
            hoje_txt = hoje_local().strftime("%d/%m/%Y")
            partes_txt = [
                f"PEDIDO DE SIMULADO – {meta_sim} – gerado pelo meu app em {hoje_txt}",
                "",
                f"Claude, monte um simulado de {sum(dist.get(m, 0) for m in escolhidas)} questões no estilo {banca_txt}, "
                "em formato de quiz interativo (alternativas de A a E, correção na hora e comentário com o artigo ou a fonte).",
                "Cobre SOMENTE os assuntos listados abaixo, que são os que eu já estudei. Não inclua nenhum outro assunto.",
                "Use questões reais de concursos anteriores quando houver e complete com questões inéditas no estilo da banca, indicando a origem de cada uma.",
                "Confira cada gabarito no texto da lei ou na fonte. No final, mostre meus acertos por matéria e por assunto, para eu registrar no app.",
                "",
                "ASSUNTOS ESTUDADOS (matéria – nº de questões):",
            ]
            for m in escolhidas:
                partes_txt.append(f"")
                partes_txt.append(f"{m} – {dist.get(m, 0)} questões")
                for a in estudados[m]:
                    partes_txt.append(f"  • {a}")
            pedido = "\n".join(partes_txt)
            
            st.subheader("Pedido para o Claude")
            st.caption("Toque no ícone de copiar no canto da caixa abaixo e cole na conversa com o Claude.")
            st.code(pedido, language=None)
            st.download_button("⬇️ Baixar o pedido (.txt)", data=pedido,
                               file_name=f"pedido_simulado_{hoje_local():%Y-%m-%d}.txt", mime="text/plain")

elif menu == "📝 Registrar Questões":
    st.header("📝 Registro de Desempenho em Exercícios")
    
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.warning("Cadastre um Objetivo e Matérias no menu '⚙️ Gerenciador' antes de lançar exercícios.")
    else:
        meta_sel = st.selectbox("Selecione o Objetivo", df_metas['nome'].tolist())
        meta_id = df_metas[df_metas['nome'] == meta_sel]['id'].values[0]
        
        df_mat = pd.read_sql_query("SELECT id, nome FROM materias WHERE meta_id = ?", conn, params=(int(meta_id),))
        
        if df_mat.empty:
            st.warning("Nenhuma matéria cadastrada para este objetivo.")
        else:
            mat_sel = st.selectbox("Selecione a Matéria", df_mat['nome'].tolist())
            mat_id = df_mat[df_mat['nome'] == mat_sel]['id'].values[0]
            
            df_top = pd.read_sql_query("SELECT id, nome FROM topicos WHERE materia_id = ? ORDER BY COALESCE(semana, 0), COALESCE(dia, 0), COALESCE(ordem, 0), id", conn, params=(int(mat_id),))
            
            if df_top.empty:
                st.warning("Nenhum tópico cadastrado nesta matéria.")
            else:
                topico_sel = st.selectbox("Selecione o Tópico", df_top['nome'].tolist())
                topico_id = df_top[df_top['nome'] == topico_sel]['id'].values[0]

                with st.form("form_ex", clear_on_submit=True):
                    col_a, col_b = st.columns(2)
                    with col_a: acertos = st.number_input("Número de Acertos", min_value=0, value=0, step=1)
                    with col_b: erros = st.number_input("Número de Erros", min_value=0, value=0, step=1)

                    if st.form_submit_button("💾 Salvar Desempenho"):
                        if acertos + erros == 0:
                            avisar("Nada foi salvo: informe pelo menos 1 acerto ou 1 erro.", "warning")
                        else:
                            try:
                                c = conn.cursor()
                                c.execute("INSERT INTO exercicios (data, topico_id, acertos, erros) VALUES (?, ?, ?, ?)",
                                          (hoje_local().strftime('%Y-%m-%d'), int(topico_id), int(acertos), int(erros)))
                                conn.commit()
                                novo_id = c.lastrowid
                                conf = conn.execute("SELECT acertos, erros FROM exercicios WHERE id = ?", (novo_id,)).fetchone()
                                if conf and conf[0] == int(acertos) and conf[1] == int(erros):
                                    total = conf[0] + conf[1]
                                    avisar(f"Salvo e conferido no banco: {conf[0]} acertos e {conf[1]} erros "
                                           f"({round(100 * conf[0] / total)}% de acerto) em \"{topico_sel.split(' · ', 1)[-1]}\".")
                                else:
                                    avisar("O app tentou salvar, mas não encontrou o registro ao conferir o banco. Tente de novo.", "error")
                            except Exception as e:
                                avisar(f"NÃO foi salvo. Erro: {e}", "error")
                        st.rerun()

                # Histórico: prova de que o registro está no banco
                st.markdown("#### 📚 Seus registros neste tópico")
                df_reg = pd.read_sql_query(
                    "SELECT id, data, acertos, erros FROM exercicios WHERE topico_id = ? ORDER BY id DESC",
                    conn, params=(int(topico_id),))
                if df_reg.empty:
                    st.info("Nenhum registro salvo neste tópico ainda.")
                else:
                    tot_a, tot_e = int(df_reg['acertos'].sum()), int(df_reg['erros'].sum())
                    st.write(f"**Total:** {tot_a} acertos · {tot_e} erros · "
                             f"**{round(100 * tot_a / max(1, tot_a + tot_e))}%** de acerto em {len(df_reg)} registro(s).")
                    mostrar = df_reg.copy()
                    mostrar['data'] = pd.to_datetime(mostrar['data']).dt.strftime('%d/%m/%Y')
                    mostrar.columns = ['Nº', 'Data', 'Acertos', 'Erros']
                    st.dataframe(mostrar, hide_index=True, use_container_width=True)
                    with st.expander("🗑️ Apagar um registro lançado errado"):
                        opcoes = {f"Nº {r.id} · {pd.to_datetime(r.data):%d/%m/%Y} · {r.acertos} acertos, {r.erros} erros": int(r.id)
                                  for r in df_reg.itertuples()}
                        escolha = st.selectbox("Registro", list(opcoes.keys()), key="ex_apagar_sel")
                        if st.button("Apagar este registro", key="ex_apagar_btn"):
                            try:
                                conn.execute("DELETE FROM exercicios WHERE id = ?", (opcoes[escolha],))
                                conn.commit()
                                ainda = conn.execute("SELECT 1 FROM exercicios WHERE id = ?", (opcoes[escolha],)).fetchone()
                                avisar("Registro apagado." if not ainda else "O registro NÃO foi apagado. Tente de novo.",
                                       "success" if not ainda else "error")
                            except Exception as e:
                                avisar(f"NÃO foi apagado. Erro: {e}", "error")
                            st.rerun()

# =============================================================================
# MENU: REDAÇÕES (notas pelos critérios do edital CBMPE 002/2026 – cargo de Oficial)
# =============================================================================
elif menu == "✍️ Redações":
    import altair as alt
    st.header("✍️ Minhas Redações")

    # Tabela 12.2 do edital (2º Tenente): pontuação máxima por aspecto
    ASPECTOS = [
        ("a1", "1. Tema, informatividade e argumentação", 8.0),
        ("a2", "2. Coesão e coerência", 8.0),
        ("a3", "3. Estrutura dissertativo-argumentativa", 7.0),
        ("a4", "4. Gramática (pontuação, grafia/legibilidade, concordância, regência, colocação)", 7.0),
    ]
    NOTA_MAX, NOTA_MIN = 30.0, 9.0          # item 12.3, b
    LINHAS_MIN, LINHAS_MAX = 15, 20          # item 12.6
    MOTIVOS_ZERO = ["Fuga ao tema", "Tipologia diferente de dissertação", "Desestruturação acentuada",
                    "Letra ilegível / espaçamento excessivo", "Identificação no texto", "Outro motivo do item 12.8"]
    AZUL, CINZA, VERMELHO = "#256abf", "#9aa0a6", "#d03b3b"

    with st.expander("📌 Regras do edital (item 12) – toque para ver", expanded=False):
        st.markdown(
            "- **Total: 30 pontos.** Abaixo de **9** = eliminado.\n"
            "- Aspectos: tema/argumentação **8** · coesão/coerência **8** · estrutura **7** · gramática **7**.\n"
            "- **15 a 20 linhas.** O que passar de 20 é desconsiderado; fora dos limites perde pontos.\n"
            "- **Nota zero:** fuga ao tema, tipologia errada, desestruturação acentuada, letra ilegível, "
            "lápis ou tinta que não seja azul/preta, identificação de qualquer tipo.")

    # ---------------- registrar ----------------
    st.subheader("➕ Registrar uma redação corrigida")
    with st.form("form_redacao", clear_on_submit=True):
        c1, c2 = st.columns([1, 3])
        with c1:
            data_red = st.date_input("Data", value=hoje_local(), format="DD/MM/YYYY")
        with c2:
            tema = st.text_input("Tema da redação")
        linhas = st.number_input("Linhas usadas na folha", min_value=0, max_value=40, value=20, step=1)
        zerada = st.checkbox("A redação levou nota ZERO (item 12.8)")
        motivo = st.selectbox("Motivo da nota zero (só se marcou acima)", MOTIVOS_ZERO)
        st.markdown("**Notas por aspecto**")
        notas = {}
        cols = st.columns(2)
        for i, (chave, nome, maximo) in enumerate(ASPECTOS):
            with cols[i % 2]:
                notas[chave] = st.number_input(f"{nome} (máx. {maximo:g})", min_value=0.0, max_value=maximo,
                                               value=0.0, step=0.25, key=f"red_{chave}")
        comentario = st.text_area("Comentário da correção (cole aqui o que eu te devolver)", height=120)

        if st.form_submit_button("💾 Salvar redação"):
            if not tema.strip():
                avisar("Nada foi salvo: escreva o tema da redação.", "warning")
            else:
                if zerada:
                    notas = {k: 0.0 for k in notas}
                total = round(sum(notas.values()), 2)
                try:
                    c = conn.cursor()
                    c.execute("""INSERT INTO redacoes (data, tema, linhas, a1, a2, a3, a4, total, zerada, motivo_zero, comentario)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                              (data_red.isoformat(), tema.strip(), int(linhas), notas["a1"], notas["a2"], notas["a3"],
                               notas["a4"], total, 1 if zerada else 0, motivo if zerada else None, comentario.strip()))
                    conn.commit()
                    conf = conn.execute("SELECT total FROM redacoes WHERE id = ?", (c.lastrowid,)).fetchone()
                    if conf is not None and abs(conf[0] - total) < 0.001:
                        situacao = "ELIMINADO (abaixo de 9)" if total < NOTA_MIN else "acima do mínimo"
                        avisar(f"Salvo e conferido: \"{tema.strip()[:60]}\" com {total:g}/30 ({situacao}).")
                    else:
                        avisar("O app tentou salvar, mas não encontrou o registro ao conferir. Tente de novo.", "error")
                except Exception as e:
                    avisar(f"NÃO foi salvo. Erro: {e}", "error")
            st.rerun()

    # ---------------- evolução ----------------
    df_red = pd.read_sql_query("SELECT * FROM redacoes ORDER BY data, id", conn)
    if df_red.empty:
        st.info("Nenhuma redação registrada ainda. Depois que eu corrigir a primeira, lance as notas aqui.")
    else:
        df_red["data_dt"] = pd.to_datetime(df_red["data"])
        df_red["n"] = range(1, len(df_red) + 1)
        ultima = df_red.iloc[-1]
        ult3 = df_red.tail(3)

        st.subheader("📈 Como estou?")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Redações", len(df_red))
        anterior = df_red.iloc[-2]["total"] if len(df_red) > 1 else None
        m2.metric("Última nota", f"{ultima['total']:g}/30",
                  None if anterior is None else f"{ultima['total'] - anterior:+g} vs. anterior")
        m3.metric("Média das 3 últimas", f"{ult3['total'].mean():.1f}/30")
        m4.metric("Melhor nota", f"{df_red['total'].max():g}/30")

        if ultima["total"] < NOTA_MIN:
            st.error(f"🔴 A última redação ficou abaixo de {NOTA_MIN:g}: na prova, isso elimina.")
        if not (LINHAS_MIN <= int(ultima["linhas"]) <= LINHAS_MAX):
            st.warning(f"⚠️ A última redação teve {int(ultima['linhas'])} linhas. O edital exige de 15 a 20.")

        # aspecto mais fraco nas 3 últimas (em % do máximo de cada um, para comparar de forma justa)
        pct = {nome: 100 * ult3[ch].mean() / mx for ch, nome, mx in ASPECTOS}
        mais_fraco = min(pct, key=pct.get)
        janela = "na última redação" if len(ult3) == 1 else f"média das {len(ult3)} últimas"
        st.info(f"🎯 Ponto a atacar agora ({janela}): **{mais_fraco}**, "
                f"com {pct[mais_fraco]:.0f}% do máximo.")

        base = alt.Chart(df_red).encode(
            x=alt.X("n:O", title="redação nº", axis=alt.Axis(labelAngle=0)))
        linha = base.mark_line(color=AZUL, strokeWidth=2,
                               point=alt.OverlayMarkDef(size=70, filled=True, color=AZUL)).encode(
            y=alt.Y("total:Q", title="nota (0 a 30)", scale=alt.Scale(domain=[0, 30])),
            tooltip=[alt.Tooltip("n:O", title="nº"), alt.Tooltip("data_dt:T", title="data", format="%d/%m/%Y"),
                     alt.Tooltip("tema:N", title="tema"), alt.Tooltip("total:Q", title="nota")])
        corte = alt.Chart(pd.DataFrame({"y": [NOTA_MIN]})).mark_rule(color=VERMELHO, strokeDash=[4, 3]).encode(y="y:Q")
        st.altair_chart((linha + corte).properties(height=220), use_container_width=True)
        st.caption("Linha azul = nota total de cada redação. Tracejado vermelho = 9 pontos (abaixo disso, eliminado).")

        longo = []
        for ch, nome, mx in ASPECTOS:
            for r in df_red.itertuples():
                longo.append({"n": r.n, "aspecto": nome.split(" (")[0], "pct": round(100 * getattr(r, ch) / mx)})
        df_l = pd.DataFrame(longo)
        asp = alt.Chart(df_l).mark_line(point=True).encode(
            x=alt.X("n:O", title="redação nº", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("pct:Q", title="% do máximo do aspecto", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("aspecto:N", legend=alt.Legend(orient="bottom", columns=1, title=None)),
            tooltip=["n:O", "aspecto:N", alt.Tooltip("pct:Q", title="% do máximo")])
        st.altair_chart(asp.properties(height=260), use_container_width=True)
        st.caption("Cada aspecto em % do seu máximo (8, 8, 7 e 7), para comparar qual está pior.")

        # ---------------- histórico ----------------
        st.subheader("📚 Histórico")
        tab = df_red.sort_values("id", ascending=False)
        mostrar = pd.DataFrame({
            "Nº": tab["n"], "Data": tab["data_dt"].dt.strftime("%d/%m/%Y"), "Tema": tab["tema"],
            "Linhas": tab["linhas"], "Tema/arg. (8)": tab["a1"], "Coesão (8)": tab["a2"],
            "Estrutura (7)": tab["a3"], "Gramática (7)": tab["a4"], "Total (30)": tab["total"],
            "Zero?": tab["motivo_zero"].fillna("")})
        st.dataframe(mostrar, hide_index=True, use_container_width=True)

        opcoes = {f"Nº {r.n} · {r.data_dt:%d/%m/%Y} · {r.tema[:50]} · {r.total:g}/30": int(r.id)
                  for r in tab.itertuples()}
        with st.expander("💬 Ver o comentário de correção de uma redação"):
            esc = st.selectbox("Redação", list(opcoes.keys()), key="red_ver_sel")
            txt = df_red.loc[df_red["id"] == opcoes[esc], "comentario"].iloc[0]
            st.markdown(txt if txt else "_Sem comentário salvo._")
        with st.expander("🗑️ Apagar uma redação lançada errado"):
            esc2 = st.selectbox("Redação", list(opcoes.keys()), key="red_apagar_sel")
            if st.button("Apagar esta redação", key="red_apagar_btn"):
                try:
                    conn.execute("DELETE FROM redacoes WHERE id = ?", (opcoes[esc2],))
                    conn.commit()
                    ainda = conn.execute("SELECT 1 FROM redacoes WHERE id = ?", (opcoes[esc2],)).fetchone()
                    avisar("Redação apagada." if not ainda else "A redação NÃO foi apagada. Tente de novo.",
                           "success" if not ainda else "error")
                except Exception as e:
                    avisar(f"NÃO foi apagada. Erro: {e}", "error")
                st.rerun()

# =============================================================================
# MENU 4: DASHBOARD DE EVOLUÇÃO
# =============================================================================
elif menu == "📊 Dashboard de Evolução":
    import altair as alt
    st.header("📊 Meu Desempenho")

    # Cores: status (crítico/fraco/forte) só para o que pede atenção; azul para quantidade; cinza para o resto
    COR_CRITICO, COR_FRACO, COR_FORTE = "#d03b3b", "#fab219", "#0ca30c"
    AZUL, AZUL_ESCURO, CINZA, CINZA_CLARO = "#256abf", "#104281", "#9aa0a6", "#e3e5e8"

    def faixa(pct, n):
        if pct is None or n < 10:
            return "⚪ pouco dado"
        return "🔴 crítico" if pct < 50 else ("🟡 fraco" if pct < 75 else "🟢 forte")

    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    if df_metas.empty:
        st.warning("Nenhum objetivo ativo. Carregue o cronograma em ⚙️ Gerenciador → 📅 Cronogramas.")
    else:
        meta_nome = st.selectbox("Objetivo", df_metas['nome'].tolist()) if len(df_metas) > 1 else df_metas['nome'].iloc[0]
        m_id = int(df_metas[df_metas['nome'] == meta_nome]['id'].values[0])
        hoje = hoje_local()
        inicio = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{m_id}", CRONO_INICIO.isoformat()))

        # Peso de cada matéria na prova e data da prova (do edital salvo; o CFO já vem definido)
        QUESTOES_CFO = {"Língua Portuguesa": 5, "Língua Estrangeira": 5, "Informática": 5, "Estatística": 5,
                        "Matemática": 5, "Física": 5, "Química": 5, "Biologia": 5, "Direito Constitucional": 8,
                        "Direito Administrativo": 7, "Legislação dos Militares de PE": 10, "Direito Penal Militar": 5}
        pesos_prova, data_prova = {}, None
        r_ed = conn.execute("SELECT conteudo FROM editais WHERE nome = ?", (meta_nome,)).fetchone()
        if r_ed:
            try:
                import json as _jd
                ed = _jd.loads(r_ed[0])
                pesos_prova = {m['nome']: float(m.get('questoes') or m.get('pontos') or 0) for m in ed.get('materias', [])
                               if m.get('tipo') != 'redacao'}
                data_prova = datetime.date.fromisoformat(ed.get('data_prova'))
            except Exception:
                pass
        if meta_nome == CRONO_META_NOME:
            pesos_prova, data_prova = QUESTOES_CFO, datetime.date(2027, 2, 28)
        SEM_QUESTOES = {"Redação", "Revisão", "Simulados"}

        # Metas (editáveis no fim da página)
        meta_h = float(get_config("meta_horas_semana", "20"))
        meta_q = int(float(get_config("meta_questoes_semana", "100")))

        # ---------------- dados ----------------
        ex = pd.read_sql_query("""SELECT e.data, e.acertos, e.erros, m.nome AS materia, t.nome AS topico
                                  FROM exercicios e JOIN topicos t ON e.topico_id = t.id JOIN materias m ON t.materia_id = m.id
                                  WHERE m.meta_id = ?""", conn, params=(m_id,))
        ex['data'] = pd.to_datetime(ex['data']).dt.date
        ex['assunto'] = ex['topico'].apply(limpar_nome_topico)
        ex['total'] = ex['acertos'] + ex['erros']
        ses = pd.read_sql_query("""SELECT s.data, s.minutos, m.nome AS materia FROM sessoes s
                                   JOIN topicos t ON s.topico_id = t.id JOIN materias m ON t.materia_id = m.id
                                   WHERE m.meta_id = ?""", conn, params=(m_id,))
        ses['data'] = pd.to_datetime(ses['data']).dt.date
        bl = pd.read_sql_query("""SELECT t.semana, t.dia, t.status, COALESCE(t.minutos_planejados, 0) AS prev,
                                         COALESCE(t.minutos_estudados, 0) AS feito, m.nome AS materia
                                  FROM topicos t JOIN materias m ON t.materia_id = m.id
                                  WHERE m.meta_id = ? AND t.semana IS NOT NULL""", conn, params=(m_id,))
        escalas = set(ler_escalas(m_id))

        # posição de hoje no cronograma (índice de dia útil)
        dias_desde = (hoje - inicio).days
        sem_hoje = dias_desde // 7
        idx_hoje = sem_hoje * 5 + min(hoje.weekday(), 5)  # no fim de semana, a semana inteira já "passou"
        bl['idx'] = (bl['semana'] - 1) * 5 + bl['dia']
        vencidos = bl[bl['idx'] < idx_hoje]
        atrasados = vencidos[vencidos['status'] != 'Concluído']

        min_dia_14 = ses.groupby('data')['minutos'].sum().to_dict() if not ses.empty else {}
        seg = hoje - datetime.timedelta(days=hoje.weekday())
        min_semana = int(ses[ses['data'] >= seg]['minutos'].sum()) if not ses.empty else 0
        esc_semana = sum(1 for d in escalas if seg <= datetime.date.fromisoformat(d) < seg + datetime.timedelta(days=5))
        meta_semana_h = max(0.0, meta_h * (5 - esc_semana) / 5)
        dias_uteis_passados = min(hoje.weekday() + 1, 5)

        def acerto(df):
            t = int(df['total'].sum()) if not df.empty else 0
            return (round(100 * df['acertos'].sum() / t) if t else None), t
        p14, n14 = acerto(ex[ex['data'] > hoje - datetime.timedelta(days=14)])
        p28, n28 = acerto(ex[(ex['data'] <= hoje - datetime.timedelta(days=14)) & (ex['data'] > hoje - datetime.timedelta(days=28))])

        # ---------------- 1. alertas ----------------
        alertas = []
        if len(atrasados):
            alertas.append(("warning", f"**{len(atrasados)} bloco(s) atrasado(s)** até ontem. Reponha no fim de semana "
                                       f"(lista em 🗓️ Cronograma Semanal)."))
        esperado = meta_semana_h * min(dias_uteis_passados, 5) / 5
        if hoje.weekday() < 5 and esperado > 0 and min_semana / 60 < 0.7 * esperado:
            alertas.append(("warning", f"**Horas abaixo do ritmo:** {min_semana / 60:.1f} h nesta semana; "
                                       f"o esperado até hoje era {esperado:.1f} h."))
        if not ex.empty:
            ult = max(ex['data'])
            if (hoje - ult).days >= 3:
                alertas.append(("warning", f"**Nenhuma questão registrada há {(hoje - ult).days} dias.**"))
        por_mat = []
        for mat, g in ex[~ex['materia'].isin(SEM_QUESTOES)].groupby('materia'):
            p, n = acerto(g)
            pa, na = acerto(g[g['data'] > hoje - datetime.timedelta(days=14)])
            pb, nb = acerto(g[(g['data'] <= hoje - datetime.timedelta(days=14)) & (g['data'] > hoje - datetime.timedelta(days=28))])
            por_mat.append((mat, p, n))
            if n >= 10 and p < 50:
                alertas.append(("error", f"**{mat} está crítica:** {p}% de acerto em {n} questões."))
            if na >= 5 and nb >= 5 and pa <= pb - 10:
                alertas.append(("warning", f"**{mat} caiu:** {pb}% → {pa}% nos últimos 14 dias."))
        if alertas:
            for tipo, txt in alertas[:5]:
                getattr(st, tipo)(txt)
        else:
            st.success("Nada pedindo atenção agora. Continue no ritmo.")

        # ---------------- 2. cartões ----------------
        c1, c2 = st.columns(2)
        c3, c4 = st.columns(2)
        horas_14 = [round(min_dia_14.get(hoje - datetime.timedelta(days=i), 0) / 60, 1) for i in range(13, -1, -1)]
        acerto_sem = []
        if not ex.empty:
            for _, g in ex.assign(sem=ex['data'].apply(lambda d: d - datetime.timedelta(days=d.weekday()))).groupby('sem'):
                acerto_sem.append(round(100 * g['acertos'].sum() / max(1, g['total'].sum())))
        c1.metric("Ritmo do cronograma", "Em dia" if not len(atrasados) else f"{len(atrasados)} atrasado(s)",
                  f"{int((vencidos['status'] == 'Concluído').sum())} de {len(vencidos)} blocos até ontem",
                  delta_color="off", delta_arrow="off", border=True)
        c2.metric("Horas nesta semana", f"{min_semana / 60:.1f} h", f"meta {meta_semana_h:.0f} h"
                  + (f" ({esc_semana} dia(s) de escala)" if esc_semana else ""), delta_color="off", delta_arrow="off",
                  border=True, chart_data=horas_14, chart_type="bar", help="Minigráfico: horas por dia nos últimos 14 dias.")
        c3.metric("Acerto (últimos 14 dias)", f"{p14}%" if p14 is not None else "–",
                  (f"{p14 - p28:+d} pontos vs 14 dias antes" if (p14 is not None and p28 is not None) else f"{n14} questões"),
                  delta_color="normal" if (p14 is not None and p28 is not None) else "off",
                  delta_arrow="auto" if (p14 is not None and p28 is not None) else "off", border=True,
                  chart_data=acerto_sem[-8:] or None, help="Minigráfico: % de acerto semana a semana.")
        if data_prova:
            c4.metric("Dias até a prova", (data_prova - hoje).days, f"{data_prova:%d/%m/%Y}",
                      delta_color="off", delta_arrow="off", border=True)

        # bullet graph das horas da semana: faixas cinza (ruim/regular/bom), barra azul, traço na meta
        if meta_semana_h > 0:
            topo = max(meta_semana_h * 1.2, min_semana / 60)
            faixas_df = pd.DataFrame({"ini": [0, meta_semana_h * 0.5, meta_semana_h * 0.8],
                                      "fim": [meta_semana_h * 0.5, meta_semana_h * 0.8, topo],
                                      "faixa": ["abaixo de 50%", "50% a 80%", "80% ou mais"]})
            base = alt.Chart(faixas_df).mark_bar(height=26).encode(
                x=alt.X("ini:Q", title="horas nesta semana", scale=alt.Scale(domain=[0, topo])), x2="fim:Q",
                color=alt.Color("faixa:N", scale=alt.Scale(domain=["abaixo de 50%", "50% a 80%", "80% ou mais"],
                                                           range=["#c9ccd1", "#dcdfe3", "#eceef0"]), legend=None),
                tooltip=["faixa"])
            barra = alt.Chart(pd.DataFrame({"h": [min_semana / 60]})).mark_bar(height=10, color=AZUL).encode(
                x="h:Q", tooltip=[alt.Tooltip("h:Q", title="estudadas (h)", format=".1f")])
            alvo = alt.Chart(pd.DataFrame({"m": [meta_semana_h]})).mark_tick(color="#202124", thickness=3, size=30).encode(
                x="m:Q", tooltip=[alt.Tooltip("m:Q", title="meta (h)", format=".0f")])
            st.altair_chart((base + barra + alvo).properties(height=60), use_container_width=True)
            st.caption("Barra azul = horas estudadas · traço preto = meta da semana · faixas: abaixo de 50%, 50 a 80% e 80% ou mais da meta.")

        # ---------------- 3. calendário de constância ----------------
        st.subheader("📅 Constância")
        ini_cal = max(inicio, hoje - datetime.timedelta(weeks=12))
        ini_cal -= datetime.timedelta(days=ini_cal.weekday())
        dias = [ini_cal + datetime.timedelta(days=i) for i in range((hoje - ini_cal).days + 1)]
        min_dia = ses.groupby('data')['minutos'].sum().to_dict() if not ses.empty else {}
        q_dia = ex.groupby('data')['total'].sum().to_dict() if not ex.empty else {}
        nomes_dia = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
        cal = pd.DataFrame([{
            "data": d.strftime("%d/%m"), "semana": d - datetime.timedelta(days=d.weekday()),
            "dia": nomes_dia[d.weekday()], "minutos": int(min_dia.get(d, 0)), "questoes": int(q_dia.get(d, 0)),
            "tipo": "Escala" if d.isoformat() in escalas else ("Estudou" if min_dia.get(d, 0) > 0 or q_dia.get(d, 0) > 0
                                                             else "Sem registro")} for d in dias])
        # grade de quadrados (HTML simples: fica igual no celular e no computador)
        def cor_dia(row):
            if row['tipo'] == "Escala":
                return "#5f6368"
            if row['tipo'] == "Sem registro":
                return CINZA_CLARO
            t = min(1.0, max(row['minutos'], 30) / 240)
            c0, c1_ = (0xb7, 0xd3, 0xf6), (0x10, 0x42, 0x81)
            return "#%02x%02x%02x" % tuple(int(c0[i] + (c1_[i] - c0[i]) * t) for i in range(3))
        cal['cor'] = cal.apply(cor_dia, axis=1)
        semanas = sorted(cal['semana'].unique())
        celula = "width:20px;height:20px;border-radius:4px;margin:2px;display:inline-block"
        html = ['<div style="overflow-x:auto"><table style="border-collapse:collapse">']
        for nd in nomes_dia:
            html.append(f'<tr><td style="font-size:11px;color:#6b7280;padding-right:6px">{nd}</td>')
            for sm in semanas:
                r = cal[(cal['semana'] == sm) & (cal['dia'] == nd)]
                if r.empty:
                    html.append(f'<td><span style="{celula}"></span></td>')
                else:
                    r = r.iloc[0]
                    dica = f"{r['data']}: {r['tipo'].lower()}, {r['minutos']} min, {r['questoes']} questões"
                    html.append(f'<td><span title="{dica}" style="{celula};background:{r["cor"]}"></span></td>')
            html.append("</tr>")
        html.append('<tr><td></td>' + "".join(
            f'<td style="font-size:10px;color:#6b7280;text-align:center">{sm:%d/%m}</td>' if i % 2 == 0 else "<td></td>"
            for i, sm in enumerate(semanas)) + "</tr></table></div>")
        legenda = (f'<div style="font-size:12px;color:#6b7280;margin-top:4px">'
                   f'<span style="{celula};background:{CINZA_CLARO};vertical-align:middle"></span> sem registro &nbsp; '
                   f'<span style="{celula};background:#b7d3f6;vertical-align:middle"></span> pouco &nbsp; '
                   f'<span style="{celula};background:{AZUL_ESCURO};vertical-align:middle"></span> 4 h ou mais &nbsp; '
                   f'<span style="{celula};background:#5f6368;vertical-align:middle"></span> escala</div>')
        st.markdown("".join(html) + legenda, unsafe_allow_html=True)
        dias_uteis = [d for d in dias if d.weekday() < 5 and d <= hoje and d >= inicio and d.isoformat() not in escalas]
        dias_ok = sum(1 for d in dias_uteis if min_dia.get(d, 0) > 0 or q_dia.get(d, 0) > 0)
        st.caption(f"Quanto mais escuro, mais tempo estudado. Dias úteis com estudo registrado: **{dias_ok} de {len(dias_uteis)}** "
                   f"(dias de escala não contam).")

        # ---------------- 4. evolução ----------------
        st.subheader("📈 Estou evoluindo?")
        if ex.empty:
            st.info("Registre questões em 📝 Registrar Questões para ver a sua evolução semana a semana.")
        else:
            ex['semana'] = pd.to_datetime(ex['data'].apply(lambda d: d - datetime.timedelta(days=d.weekday())))
            ev = ex.groupby('semana').agg(acertos=('acertos', 'sum'), total=('total', 'sum')).reset_index()
            ev['acerto'] = (100 * ev['acertos'] / ev['total']).round(0)
            bandas = pd.DataFrame({"de": [0, 50, 75], "ate": [50, 75, 100], "faixa": ["crítico", "fraco", "forte"]})
            fundo = alt.Chart(bandas).mark_rect(opacity=0.5).encode(
                y=alt.Y("de:Q", scale=alt.Scale(domain=[0, 100]), title="% de acerto"), y2="ate:Q",
                color=alt.Color("faixa:N", scale=alt.Scale(domain=["crítico", "fraco", "forte"], range=["#e6e7ea", "#f1f2f4", "#fafafa"]),
                                legend=None))
            rotulos = alt.Chart(bandas).mark_text(align="left", dx=4, dy=10, color="#6b7280", fontSize=11).encode(
                y="ate:Q", text="faixa:N", x=alt.value(0))
            linha = alt.Chart(ev).mark_line(color=AZUL, strokeWidth=2, point=alt.OverlayMarkDef(size=70, filled=True, color=AZUL)).encode(
                x=alt.X("semana:T", title=None, axis=alt.Axis(format="%d/%m", tickCount="week")),
                y=alt.Y("acerto:Q", scale=alt.Scale(domain=[0, 100])),
                tooltip=[alt.Tooltip("semana:T", title="semana de", format="%d/%m"), alt.Tooltip("acerto:Q", title="% acerto"),
                         alt.Tooltip("total:Q", title="questões")])
            st.altair_chart((fundo + rotulos + linha).properties(height=220), use_container_width=True)
            qs = alt.Chart(ev).mark_bar(color=CINZA, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=22).encode(
                x=alt.X("semana:T", title=None, axis=alt.Axis(format="%d/%m", tickCount="week")),
                y=alt.Y("total:Q", title="questões na semana"),
                tooltip=[alt.Tooltip("semana:T", title="semana de", format="%d/%m"), alt.Tooltip("total:Q", title="questões")])
            meta_linha = alt.Chart(pd.DataFrame({"q": [meta_q]})).mark_rule(color="#202124", strokeDash=[4, 3]).encode(y="q:Q")
            st.altair_chart((qs + meta_linha).properties(height=160), use_container_width=True)
            st.caption(f"Linha azul = seu % de acerto por semana (faixas: crítico < 50%, fraco 50–75%, forte > 75%). "
                       f"Barras = questões feitas por semana; tracejado = meta de {meta_q}.")

        # ---------------- 5. matérias ----------------
        st.subheader("📚 Matérias – da que mais precisa de atenção para a que menos")
        linhas = []
        for mat in sorted(set(bl['materia']) - SEM_QUESTOES):
            g = ex[ex['materia'] == mat]
            p, n = acerto(g)
            semanal = []
            if not g.empty:
                gs = g.assign(sem=g['data'].apply(lambda d: d - datetime.timedelta(days=d.weekday()))).groupby('sem')
                semanal = [round(100 * x['acertos'].sum() / x['total'].sum()) for _, x in gs][-8:]
            bm = bl[bl['materia'] == mat]
            prev_ate = bm[bm['idx'] < idx_hoje]['prev'].sum()
            linhas.append({"Situação": faixa(p, n), "Matéria": mat, "Acerto": p,
                           "Tendência": semanal, "Questões": n,
                           "Horas": round(bm['feito'].sum() / 60, 1), "Previsto até hoje (h)": round(prev_ate / 60, 1),
                           "Na prova": int(pesos_prova.get(mat, 0)) or None, "_ord": p if p is not None else 999})
        tab = pd.DataFrame(linhas).sort_values(["_ord", "Na prova"], ascending=[True, False]).drop(columns="_ord")
        tab = tab[["Situação", "Matéria", "Acerto", "Questões", "Tendência", "Horas", "Previsto até hoje (h)", "Na prova"]]
        st.dataframe(tab, hide_index=True, use_container_width=True, column_config={
            "Acerto": st.column_config.ProgressColumn("Acerto (%)", min_value=0, max_value=100, format="%d%%", color=AZUL),
            "Tendência": st.column_config.LineChartColumn("Tendência (semanas)", y_min=0, y_max=100),
            "Horas": st.column_config.NumberColumn("Horas estudadas", format="%.1f"),
            "Na prova": st.column_config.NumberColumn("Questões na prova")})
        st.caption("⚪ pouco dado = menos de 10 questões registradas (ainda não dá para concluir). "
                   "🔴 abaixo de 50% · 🟡 de 50% a 75% · 🟢 acima de 75% (mesmos cortes do QConcursos).")

        # ---------------- 6. mapa de dificuldades e facilidades ----------------
        st.subheader("🎯 Mapa de dificuldades e facilidades")
        if ex.empty:
            st.info("Aparece quando houver questões registradas.")
        else:
            ass = ex.groupby(['materia', 'assunto']).agg(acertos=('acertos', 'sum'), total=('total', 'sum')).reset_index()
            ass = ass[ass['total'] >= 5]
            if ass.empty:
                st.info("Registre pelo menos 5 questões em um assunto para ele entrar no mapa.")
            else:
                ass['Acerto'] = (100 * ass['acertos'] / ass['total']).round(0).astype(int)
                ass = ass.rename(columns={'materia': 'Matéria', 'assunto': 'Assunto', 'total': 'Questões'})
                cfg = {"Acerto": st.column_config.ProgressColumn("Acerto (%)", min_value=0, max_value=100, format="%d%%", color=AZUL)}
                st.markdown("**🔻 Revisar primeiro (menor acerto)**")
                st.dataframe(ass.sort_values('Acerto').head(5)[['Assunto', 'Acerto', 'Questões', 'Matéria']],
                             hide_index=True, use_container_width=True, column_config=cfg)
                st.markdown("**🔺 Já firmes (maior acerto)**")
                st.dataframe(ass.sort_values('Acerto', ascending=False).head(5)[['Assunto', 'Acerto', 'Questões', 'Matéria']],
                             hide_index=True, use_container_width=True, column_config=cfg)

        # ---------------- 7. onde você perde mais pontos ----------------
        if pesos_prova:
            st.subheader("💸 Onde você perde mais pontos na prova")
            risco = [{"Matéria": m, "Perdidas": round((100 - p) / 100 * pesos_prova[m], 1), "acerto": p, "n": n}
                     for m, p, n in por_mat if m in pesos_prova and n >= 5]
            if not risco:
                st.info("Aparece quando houver pelo menos 5 questões registradas numa matéria.")
            else:
                dr = pd.DataFrame(risco).sort_values("Perdidas", ascending=False)
                ch = alt.Chart(dr).mark_bar(color=AZUL, cornerRadiusTopRight=4, cornerRadiusBottomRight=4, height=18).encode(
                    x=alt.X("Perdidas:Q", title="questões que você perderia na prova, no seu acerto atual"),
                    y=alt.Y("Matéria:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
                    tooltip=["Matéria", alt.Tooltip("Perdidas:Q", title="questões perdidas"),
                             alt.Tooltip("acerto:Q", title="% acerto"), alt.Tooltip("n:Q", title="questões feitas")])
                txt = ch.mark_text(align="left", dx=4, color="#3c4043").encode(text=alt.Text("Perdidas:Q", format=".1f"))
                st.altair_chart((ch + txt).properties(height=max(120, 34 * len(dr))), use_container_width=True)
                sem_dado = [m for m in pesos_prova if m not in set(dr['Matéria'])]
                st.caption("Cálculo: (100% − seu acerto) × questões da matéria no edital. O topo da lista é onde "
                           "estudar rende mais pontos. Sem dados ainda: " + (", ".join(sem_dado) if sem_dado else "nenhuma") + ".")

        # ---------------- metas ----------------
        with st.expander("⚙️ Ajustar minhas metas"):
            nh = st.number_input("Meta de horas por semana", min_value=1.0, max_value=80.0, value=meta_h, step=1.0)
            nq = st.number_input("Meta de questões por semana", min_value=0, max_value=1000, value=meta_q, step=10)
            if st.button("💾 Salvar metas"):
                set_config("meta_horas_semana", nh)
                set_config("meta_questoes_semana", nq)
                ok_h = float(get_config("meta_horas_semana", "0")) == float(nh)
                avisar(f"Metas salvas: {nh:.0f} h e {nq} questões por semana." if ok_h else "As metas NÃO foram salvas. Tente de novo.",
                       "success" if ok_h else "error")
                st.rerun()

# =============================================================================
# MENU 5: GERENCIADOR
# =============================================================================
elif menu == "⚙️ Gerenciador":
    st.header("⚙️ Gerenciador do Sistema")
    
    t7, t6 = st.tabs(["🩺 Verificar dados", "📅 Cronogramas"])

    with t7:
        st.subheader("🩺 O que está salvo no app")
        st.caption("Tudo abaixo é lido agora do banco de dados. Se um número aqui não bater com o que você registrou, me avise.")
        _nv = nuvem_estado()
        if _nv["ativa"] and _nv["status"] == "ok":
            try:
                _q = pd.to_datetime(_nv["ultima"]).tz_convert("America/Recife").strftime("%d/%m/%Y %H:%M")
            except Exception:
                _q = str(_nv["ultima"])
            st.success(f"☁️ Guarda na nuvem: **ativa**. Última cópia: **{_q}**.")
        elif _nv["ativa"] and _nv["status"] == "vazia":
            st.info("☁️ Guarda na nuvem ativa, aguardando a primeira cópia.")
        elif _nv["ativa"]:
            st.error(f"☁️ Guarda na nuvem com problema: {_nv['erro'][:200]}")
        else:
            st.warning("☁️ Guarda na nuvem: desligada.")
        criado = get_config("banco_criado_em", "")
        if criado:
            st.write(f"**Banco de dados ativo desde:** {criado}")
        cont = {
            "Objetivos": "SELECT COUNT(*) FROM metas",
            "Blocos do cronograma": "SELECT COUNT(*) FROM topicos WHERE semana IS NOT NULL",
            "Blocos concluídos": "SELECT COUNT(*) FROM topicos WHERE status = 'Concluído'",
            "Blocos parciais": "SELECT COUNT(*) FROM topicos WHERE status = 'Parcial'",
            "Minutos estudados (total)": "SELECT COALESCE(SUM(minutos_estudados), 0) FROM topicos",
            "Registros de questões": "SELECT COUNT(*) FROM exercicios",
            "Questões resolvidas": "SELECT COALESCE(SUM(acertos + erros), 0) FROM exercicios",
            "Orientações que você editou": "SELECT COUNT(*) FROM orientacoes WHERE origem = 'usuario'",
        }
        cols = st.columns(2)
        for i, (rot, q) in enumerate(cont.items()):
            cols[i % 2].metric(rot, conn.execute(q).fetchone()[0])
        st.markdown("**Últimos registros de questões**")
        df_ult = pd.read_sql_query("""SELECT e.id AS "Nº", e.data AS Data, m.nome AS Matéria, t.nome AS Tópico,
                                       e.acertos AS Acertos, e.erros AS Erros
                                FROM exercicios e JOIN topicos t ON e.topico_id = t.id JOIN materias m ON t.materia_id = m.id
                                ORDER BY e.id DESC LIMIT 10""", conn)
        if df_ult.empty:
            st.info("Nenhuma questão registrada ainda.")
        else:
            st.dataframe(df_ult, hide_index=True, use_container_width=True)
        st.markdown("**Últimos blocos marcados**")
        df_bl = pd.read_sql_query("""SELECT t.nome AS Bloco, t.status AS Status, t.minutos_estudados AS Minutos
                                FROM topicos t WHERE t.status != 'Pendente' AND t.semana IS NOT NULL
                                ORDER BY t.semana DESC, t.dia DESC, t.ordem DESC LIMIT 10""", conn)
        if df_bl.empty:
            st.info("Nenhum bloco marcado como concluído ou parcial ainda.")
        else:
            st.dataframe(df_bl, hide_index=True, use_container_width=True)
        st.caption("Com a nuvem ativa, cada gravação é guardada fora do Streamlit (as 30 últimas versões ficam "
                   "guardadas). O backup em 📅 Cronogramas continua disponível como segurança extra.")

    with t6:
        st.subheader("📅 Carregar o Cronograma CFO CBMPE 2027")
        st.write("Cria o objetivo **CFO CBMPE 2027** com 15 matérias e todos os blocos das 20 semanas "
                 "(12/10/2026 a 26/02/2027), cada um com semana, dia, bloco e minutos previstos.")
        c = conn.cursor()
        c.execute("SELECT id FROM metas WHERE nome = ?", (CRONO_META_NOME,))
        ja_existe = c.fetchone() is not None
        if ja_existe:
            st.warning("O cronograma já está carregado. Recarregar APAGA o progresso e as questões registradas nele.")
            confirmar = st.checkbox("Entendi. Quero apagar e carregar de novo.")
            if st.button("🔄 Recarregar cronograma", disabled=not confirmar):
                n = carregar_cronograma_cfo(conn, substituir=True)
                avisar(f"Cronograma recarregado: {n} blocos.", "success")
                st.rerun()
        else:
            if st.button("🚀 Carregar cronograma", type="primary"):
                n = carregar_cronograma_cfo(conn)
                avisar(f"Cronograma carregado: {n} blocos. Veja em '🗓️ Cronograma Semanal'.", "success")
                st.rerun()

        st.markdown("---")
        st.subheader("📤 Importar cronograma de outro edital")
        st.write("Envie o edital ao Claude e peça o arquivo **no formato do app**. Ele devolve um **.json**; envie aqui. "
                 "Se for um arquivo de **edital** (matérias e tópicos), ele vai para '🧭 Planejar Estudos'. "
                 "Se for um **cronograma pronto** (blocos com dia e hora), ele é importado direto.")
        arq_crono = st.file_uploader("Arquivo do cronograma (.json)", type=["json"], key="up_crono")
        eh_edital = False
        if arq_crono is not None:
            import json as _json
            try:
                _bruto = _json.loads(arq_crono.getvalue().decode("utf-8-sig"))
                eh_edital = isinstance(_bruto, dict) and "materias" in _bruto
            except Exception:
                _bruto = None
        eh_orient = arq_crono is not None and isinstance(_bruto, dict) and "orientacoes" in _bruto
        if eh_orient:
            itens_or, erros_or = ler_arquivo_orientacoes(_bruto)
            if erros_or:
                st.error("Não consegui ler as orientações. Problemas encontrados:")
                for e in erros_or:
                    st.write(f"- {e}")
            else:
                st.success(f"Arquivo de orientações conferido: {len(itens_or)} orientações.")
                st.dataframe(pd.DataFrame([{"Matéria": m, "Tópico": t} for m, t, _ in itens_or]),
                             use_container_width=True, hide_index=True)
                if st.button("✅ Salvar estas orientações", type="primary"):
                    for m, t, txt in itens_or:
                        salvar_orientacao(conn, m, t, txt)
                    st.success("Orientações salvas! Elas aparecem embaixo de cada bloco em '📅 Meta & Rotina do Dia'.")
        elif arq_crono is not None and eh_edital:
            edital_lido, erros_ed = ler_arquivo_edital(_bruto)
            if erros_ed:
                st.error("Não consegui ler o edital. Problemas encontrados:")
                for e in erros_ed:
                    st.write(f"- {e}")
            else:
                st.success(f"Edital conferido: **{edital_lido['objetivo']}** · prova em "
                           f"{datetime.date.fromisoformat(edital_lido['data_prova']):%d/%m/%Y}")
                st.dataframe(pd.DataFrame([{"Matéria": m["nome"], "Pontos": m["pontos"], "Prioridade sugerida": m["prioridade"],
                                            "Tópicos": len(m["topicos"])} for m in edital_lido["materias"]]),
                             use_container_width=True, hide_index=True)
                if st.button("✅ Salvar este edital", type="primary"):
                    salvar_edital(conn, edital_lido)
                    st.success("Edital salvo! Agora vá em '🧭 Planejar Estudos' para marcar seu conhecimento e gerar o cronograma.")
        elif arq_crono is not None:
            dados_crono, erros_crono = ler_arquivo_cronograma(arq_crono.getvalue())
            if erros_crono:
                st.error("Não consegui ler o arquivo. Problemas encontrados:")
                for e in erros_crono:
                    st.write(f"- {e}")
            else:
                itens_crono = dados_crono["itens"]
                df_prev = pd.DataFrame(itens_crono, columns=["Semana", "Dia", "Ordem", "Bloco", "Minutos", "Matéria", "Tópico"])
                n_sem = int(df_prev["Semana"].max())
                fim_crono = dados_crono["inicio"] + datetime.timedelta(weeks=n_sem - 1, days=4)
                st.success(f"Arquivo conferido: **{dados_crono['objetivo']}**")
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("Semanas", n_sem)
                p2.metric("Blocos", len(df_prev))
                p3.metric("Matérias", df_prev["Matéria"].nunique())
                p4.metric("Horas", f"{df_prev['Minutos'].sum() / 60:.0f} h")
                st.caption(f"De {dados_crono['inicio']:%d/%m/%Y} a {fim_crono:%d/%m/%Y}"
                           + (f" · prova em {dados_crono['data_prova']}" if dados_crono['data_prova'] else ""))
                st.markdown("**Horas por matéria (confira antes de importar):**")
                resumo = (df_prev.groupby("Matéria")["Minutos"].sum() / 60).round(1).sort_values(ascending=False)
                st.dataframe(resumo.rename("Horas").reset_index(), use_container_width=True, hide_index=True)
                with st.expander("Ver os blocos da semana 1"):
                    df_s1 = df_prev[df_prev["Semana"] == 1].copy()
                    df_s1["Dia"] = df_s1["Dia"].apply(lambda d: DIAS_SEMANA[int(d)])
                    st.dataframe(df_s1.drop(columns=["Semana", "Ordem"]), use_container_width=True, hide_index=True)
                
                c.execute("SELECT id FROM metas WHERE nome = ?", (dados_crono["objetivo"],))
                existe_obj = c.fetchone() is not None
                pode_importar = True
                if existe_obj:
                    st.warning(f"Já existe um objetivo chamado '{dados_crono['objetivo']}'. Importar APAGA o progresso dele.")
                    pode_importar = st.checkbox("Entendi. Quero substituir.", key="conf_subst_crono")
                if st.button("✅ Importar este cronograma", type="primary", disabled=not pode_importar):
                    n = carregar_cronograma(conn, dados_crono["objetivo"], dados_crono["inicio"], itens_crono,
                                            dados_crono["tipo"], substituir=existe_obj)
                    avisar(f"Cronograma importado: {n} blocos. Veja em '🗓️ Cronograma Semanal'.", "success")
                    st.rerun()
        st.download_button("⬇️ Baixar modelo (cronograma CFO em .json)", data=gerar_json_cronograma_cfo(),
                           file_name="modelo_cronograma.json", mime="application/json")

        st.markdown("---")
        st.subheader("💾 Backup do banco de dados")
        st.write("Baixe uma cópia do seu progresso de vez em quando. Se o servidor reiniciar e os dados sumirem, "
                 "basta enviar o arquivo de volta aqui.")
        with open(DB_PATH, "rb") as f_db:
            st.download_button("⬇️ Baixar backup (.db)", data=f_db.read(),
                               file_name=f"backup_estudos_{hoje_local():%Y-%m-%d}.db",
                               mime="application/octet-stream")
        arquivo_backup = st.file_uploader("Restaurar a partir de um backup (.db)", type=["db"])
        if arquivo_backup is not None:
            st.warning("Restaurar substitui TODOS os dados atuais pelos dados do arquivo enviado.")
            if st.button("♻️ Restaurar este backup"):
                conteudo = arquivo_backup.getvalue()
                if not conteudo.startswith(b"SQLite format 3"):
                    st.error("Esse arquivo não é um banco de dados válido.")
                else:
                    conn.close()  # fecha a conexão antes de trocar o arquivo
                    with open(DB_PATH, "wb") as f_out:
                        f_out.write(conteudo)
                    init_db()
                    avisar("Backup restaurado!", "success")
                    st.rerun()



        st.markdown("---")
        with st.expander("🗑️ Excluir dados (use com cuidado)"):
            st.warning("Isto apaga de verdade. Baixe o backup acima antes.")
            df_metas_del = pd.read_sql_query("SELECT id, nome FROM metas", conn)
            if df_metas_del.empty:
                st.info("Nenhum dado cadastrado no momento.")
            else:
                sel_meta_del = st.selectbox("Objetivo:", df_metas_del['nome'].tolist(), key="del_meta")
                m_id_del = int(df_metas_del[df_metas_del['nome'] == sel_meta_del]['id'].values[0])
                df_mats_del = pd.read_sql_query("SELECT id, nome FROM materias WHERE meta_id = ?", conn, params=(m_id_del,))
                opcoes_del = ["O objetivo inteiro (matérias, blocos e questões)"] + [f"Só a matéria: {nm}" for nm in df_mats_del['nome']]
                o_que = st.selectbox("O que apagar:", opcoes_del, key="del_oque")
                conf_del = st.checkbox(f"Confirmo que quero apagar: {o_que} de \"{sel_meta_del}\"", key="del_conf")
                if st.button("❌ Apagar", disabled=not conf_del, key="del_btn"):
                    try:
                        if o_que == opcoes_del[0]:
                            conn.execute("DELETE FROM metas WHERE id = ?", (m_id_del,))
                            conn.commit()
                            sobrou = conn.execute("SELECT COUNT(*) FROM metas WHERE id = ?", (m_id_del,)).fetchone()[0]
                        else:
                            nome_m = o_que.split(": ", 1)[1]
                            conn.execute("DELETE FROM materias WHERE meta_id = ? AND nome = ?", (m_id_del, nome_m))
                            conn.commit()
                            sobrou = conn.execute("SELECT COUNT(*) FROM materias WHERE meta_id = ? AND nome = ?", (m_id_del, nome_m)).fetchone()[0]
                        avisar(f"Apagado e conferido: {o_que}." if sobrou == 0 else "NÃO foi apagado. Tente de novo.",
                               "success" if sobrou == 0 else "error")
                    except Exception as e:
                        avisar(f"NÃO foi apagado. Erro: {e}", "error")
                    st.rerun()

conn.close()