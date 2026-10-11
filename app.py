import streamlit as st
import pandas as pd
import datetime
import sqlite3
import time
import os
import json
import base64
import hashlib
import threading
from zoneinfo import ZoneInfo
try:
    import requests
except ImportError:  # sem a biblioteca, o app funciona normalmente, só sem a cópia na nuvem
    requests = None

st.set_page_config(page_title="Sistema de Estudos & Carreira", layout="wide", page_icon="🛡️")

# -----------------------------------------------------------------------------
# BANCO DE DADOS DINÂMICO (CAMINHO ABSOLUTO FIXO)
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "estudos_master.db")

# NOVO: o servidor do Streamlit usa o horário de Londres (UTC). Sem isto, depois das 21h
# o app achava que já era o dia seguinte. Agora tudo usa o horário do Recife.
FUSO = ZoneInfo("America/Recife")

_HOJE_TESTE = os.environ.get("APP_HOJE_TESTE")  # só para testes automáticos; no uso normal fica vazio

def hoje():
    if _HOJE_TESTE:
        return datetime.date.fromisoformat(_HOJE_TESTE)
    return datetime.datetime.now(FUSO).date()

def agora():
    return datetime.datetime.now(FUSO)

# -----------------------------------------------------------------------------
# NOVO: CÓPIA AUTOMÁTICA NA NUVEM (repositório PRIVADO no GitHub)
# O banco continua sendo o arquivo SQLite; a cada gravação, uma cópia vai para o
# GitHub. Se o Streamlit reiniciar e apagar o arquivo, o app baixa a cópia sozinho.
# Cada envio vira uma versão no histórico do repositório (dá para voltar no tempo).
# -----------------------------------------------------------------------------
@st.cache_resource
def estado_nuvem():
    return {"estado": "desligada", "ultimo_envio": None, "erro": "", "bloqueada": False,
            "sha": None, "ultimo_hash": None, "cfg": None, "restaurado": False,
            "lock": threading.Lock(), "evento": threading.Event(), "thread": None}

def _config_nuvem():
    try:
        s = st.secrets["github_backup"]
        return {"token": str(s["token"]).strip(), "repo": str(s["repo"]).strip(),
                "arquivo": str(s.get("arquivo", "estudos_master.db")).strip(),
                "branch": str(s.get("branch", "main")).strip()}
    except Exception:
        return None

def _cabecalhos(cfg, bruto=False):
    return {"Authorization": f"Bearer {cfg['token']}", "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github.raw+json" if bruto else "application/vnd.github+json"}

def _url_nuvem(cfg):
    base = os.environ.get("APP_NUVEM_URL_TESTE", "https://api.github.com")  # só para testes automáticos
    return f"{base}/repos/{cfg['repo']}/contents/{cfg['arquivo']}"

def baixar_da_nuvem(cfg):
    """Devolve os bytes do banco guardado na nuvem, ou None se ainda não houver cópia."""
    r = requests.get(_url_nuvem(cfg), headers=_cabecalhos(cfg, bruto=True), params={"ref": cfg["branch"]}, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    if not r.content.startswith(b"SQLite format 3"):
        raise ValueError("o arquivo guardado na nuvem não é um banco de dados válido")
    return r.content

def banco_local_tem_dados():
    """True se o banco deste servidor já tem algo seu (objetivos, questões ou itens estudados)."""
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        return False
    try:
        con = sqlite3.connect(DB_PATH)
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        tem = False
        if "metas" in tabelas:
            tem = con.execute("SELECT COUNT(*) FROM metas").fetchone()[0] > 0
        if not tem and "questoes" in tabelas:
            tem = con.execute("SELECT COUNT(*) FROM questoes").fetchone()[0] > 0
        if not tem and "edital_itens" in tabelas:
            tem = con.execute("SELECT COUNT(*) FROM edital_itens WHERE teoria = 1").fetchone()[0] > 0
        con.close()
        return tem
    except Exception:
        return False

@st.cache_resource
def restaurar_da_nuvem_ao_iniciar():
    """Roda uma única vez quando o servidor liga. Se o banco local sumiu, traz a cópia da nuvem."""
    est = estado_nuvem()
    cfg = _config_nuvem()
    est["cfg"] = cfg
    if not cfg or requests is None:
        est["estado"] = "desligada"
        return True
    if banco_local_tem_dados():
        est["estado"] = "ligada"
        return True
    try:
        conteudo = baixar_da_nuvem(cfg)
        if conteudo:
            with open(DB_PATH, "wb") as f:
                f.write(conteudo)
            est["restaurado"] = True
        est["estado"] = "ligada"
    except Exception as e:
        # Não deixa enviar nada: senão um banco vazio poderia apagar a cópia boa da nuvem.
        est["estado"] = "erro"
        est["bloqueada"] = True
        est["erro"] = f"Não consegui baixar a cópia da nuvem ({e}). Os envios foram pausados para proteger seus dados."
    return True

def _enviar_agora(est):
    cfg = est["cfg"]
    if not cfg or est["bloqueada"] or not os.path.exists(DB_PATH):
        return
    tmp = DB_PATH + ".envio"
    origem, destino = sqlite3.connect(DB_PATH), sqlite3.connect(tmp)
    origem.backup(destino)  # cópia consistente, mesmo com o app gravando
    origem.close()
    destino.close()
    with open(tmp, "rb") as f:
        dados = f.read()
    os.remove(tmp)
    resumo = hashlib.sha256(dados).hexdigest()
    if resumo == est["ultimo_hash"]:
        return
    for tentativa in range(2):
        if est["sha"] is None:
            r = requests.get(_url_nuvem(cfg), headers=_cabecalhos(cfg), params={"ref": cfg["branch"]}, timeout=30)
            if r.status_code == 200:
                est["sha"] = r.json().get("sha")
            elif r.status_code != 404:
                r.raise_for_status()
        corpo = {"message": f"Cópia automática {agora():%d/%m/%Y %H:%M:%S}",
                 "content": base64.b64encode(dados).decode("ascii"), "branch": cfg["branch"]}
        if est["sha"]:
            corpo["sha"] = est["sha"]
        r = requests.put(_url_nuvem(cfg), headers=_cabecalhos(cfg), json=corpo, timeout=60)
        if r.status_code in (409, 422) and tentativa == 0:
            est["sha"] = None  # a versão mudou: busca de novo e tenta mais uma vez
            continue
        r.raise_for_status()
        est["sha"] = r.json()["content"]["sha"]
        est["ultimo_hash"] = resumo
        est["ultimo_envio"] = agora()
        est["erro"] = ""
        return

def _trabalhador_nuvem(est):
    while True:
        est["evento"].wait()
        time.sleep(2)  # junta várias gravações seguidas num envio só
        est["evento"].clear()
        try:
            with est["lock"]:
                _enviar_agora(est)
        except Exception as e:
            est["erro"] = f"Falha ao enviar para a nuvem ({e}). Vou tentar de novo na próxima gravação."

def agendar_envio():
    est = estado_nuvem()
    if est["estado"] != "ligada" or est["bloqueada"] or requests is None:
        return
    if est["thread"] is None or not est["thread"].is_alive():
        est["thread"] = threading.Thread(target=_trabalhador_nuvem, args=(est,), daemon=True)
        est["thread"].start()
    est["evento"].set()

class ConexaoComNuvem(sqlite3.Connection):
    """Conexão normal do SQLite que, depois de cada gravação, agenda a cópia na nuvem."""
    def commit(self):
        super().commit()
        try:
            agendar_envio()
        except Exception:
            pass

restaurar_da_nuvem_ao_iniciar()

def get_db():
    conn = sqlite3.connect(DB_PATH, factory=ConexaoComNuvem)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

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
    c.execute('''CREATE TABLE IF NOT EXISTS editais (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT UNIQUE,
                    conteudo TEXT,
                    ajustes TEXT
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

    # NOVO: itens do edital (checklist), registro de questões e escalas.
    # Ficam ligados ao NOME do objetivo, e não ao cronograma: recarregar o cronograma
    # não apaga o checklist nem as questões registradas.
    c.execute('''CREATE TABLE IF NOT EXISTS edital_itens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    objetivo TEXT,
                    materia TEXT,
                    ordem INTEGER,
                    item TEXT,
                    prioridade TEXT DEFAULT 'Média',
                    teoria INTEGER DEFAULT 0,
                    resumo INTEGER DEFAULT 0,
                    material TEXT DEFAULT '',
                    data_teoria TEXT,
                    n_revisoes INTEGER DEFAULT 0,
                    proxima_revisao TEXT,
                    UNIQUE(objetivo, materia, item)
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS questoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT,
                    objetivo TEXT,
                    materia TEXT,
                    item_id INTEGER,
                    total INTEGER,
                    acertos INTEGER,
                    fonte TEXT,
                    erro_conteudo INTEGER DEFAULT 0,
                    erro_interpretacao INTEGER DEFAULT 0,
                    erro_atencao INTEGER DEFAULT 0,
                    erro_tempo INTEGER DEFAULT 0,
                    obs TEXT DEFAULT ''
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS revisoes_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT,
                    item_id INTEGER,
                    etapa INTEGER,
                    resultado TEXT,
                    proxima TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS escalas (
                    data TEXT PRIMARY KEY,
                    obs TEXT
                )''')
    # NOVO: cronômetro de tempo líquido dos blocos (Iniciar / Pausar / Finalizar)
    c.execute('''CREATE TABLE IF NOT EXISTS cronometro_bloco (
                    topico_id INTEGER PRIMARY KEY,
                    status TEXT,
                    inicio_trecho REAL,
                    acumulado REAL DEFAULT 0,
                    pausas INTEGER DEFAULT 0,
                    iniciado_em TEXT
                )''')
    # NOVO: cada sessão de estudo finalizada, com a data em que você estudou de verdade
    c.execute('''CREATE TABLE IF NOT EXISTS sessoes_estudo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT,
                    objetivo TEXT,
                    materia TEXT,
                    topico_id INTEGER,
                    minutos INTEGER,
                    pausas INTEGER DEFAULT 0,
                    inicio TEXT,
                    fim TEXT,
                    origem TEXT
                )''')

    # Auto-correção para "portugês" -> "Português" no banco
    c.execute("UPDATE materias SET nome = REPLACE(nome, 'portugês', 'português') WHERE nome LIKE '%portugês%'")
    c.execute("UPDATE materias SET nome = REPLACE(nome, 'Portugês', 'Português') WHERE nome LIKE '%Portugês%'")
    c.execute("UPDATE materias SET nome = REPLACE(nome, 'PORTUGÊS', 'PORTUGUÊS') WHERE nome LIKE '%PORTUGÊS%'")
    
    conn.commit()
    conn.close()

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
    
    # NOVO: usa as questões registradas por matéria (as do formato antigo já foram trazidas para cá)
    query_ex = """
        SELECT q.acertos, q.total - q.acertos as erros
        FROM questoes q
        JOIN materias m ON m.id = ?
        JOIN metas me ON m.meta_id = me.id
        WHERE q.objetivo = me.nome AND q.materia = m.nome
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

_LEG = ["Estatuto (Lei 6.783): disposições gerais, hierarquia e disciplina", "Estatuto: cargo e função, obrigações e deveres",
        "Estatuto: direitos, prerrogativas, férias e licenças", "Estatuto: situações especiais e proteção social",
        "Estatuto: desligamento, exclusão, tempo de serviço", "Cód. Disciplinar (Lei 11.817): regime disciplinar e transgressões",
        "Cód. Disciplinar: penas e medidas administrativas", "Cód. Disciplinar: processo, recursos, comissões recursais",
        "Cód. Disciplinar: cancelamento, recompensas, transgressões em espécie", "Decreto 50.014/2020",
        "Lei 15.187/2013 (CBMPE): generalidades e organização", "Lei 15.187/2013: atribuições e pessoal",
        "Lei 14.751/2023: princípios, competências, quadros", "Lei 14.751/2023: direitos, garantias, ingresso",
        "2ª passada: Estatuto + Cód. Disciplinar em questões", "2ª passada: Decreto, Lei 15.187 e Lei 14.751 em questões"]
# Constitucional: (terça, sexta) nas semanas ímpares; só terça nas pares
_CF = [("Constituição: conceito, classificação, histórico, elementos e estrutura", "Poder constituinte, mutação, recepção e repristinação"), ("Eficácia das normas; princípios fundamentais",),
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
# NOVO: rodízio revisto para cobrir todos os itens do edital de exatas, informática e idioma
_ROT = [
        ('Mat: conjuntos numéricos, divisibilidade e fatoração', 'Fís: grandezas, SI, notação científica, vetores e cinemática', 'Quím: química do fogo e da combustão; produtos perigosos e FDS'),
        ('Est: conceitos, população, amostra e apresentação de dados', 'Bio: citologia e metabolismo energético', 'Info: internet, intranet, navegadores e computação em nuvem'),
        ('Inglês/Espanhol: interpretação de textos e vocabulário', 'Mat: razão, proporção, porcentagem e juros', 'Fís: dinâmica: Leis de Newton, atrito e movimento circular'),
        ('Quím: substâncias, misturas e separação; átomo e tabela periódica', 'Est: medidas de centralidade e de posição', 'Bio: genética, síntese proteica, biotecnologia e ética'),
        ('Info: segurança da informação: malwares, phishing, criptografia', 'Inglês/Espanhol: gramática I (EN: substantivos, adjetivos, artigos, pronomes · ES: determinantes, substantivos, adjetivos, pronomes)', 'Mat: PA, PG e princípios de contagem'),
        ('Fís: hidrostática: Stevin, Pascal e Arquimedes (empuxo)', 'Quím: ligações, forças intermoleculares, Lewis, nox e funções inorgânicas', 'Est: medidas de dispersão, histograma e boxplot'),
        ('Bio: evolução, classificação dos seres vivos e embriologia', 'Info: backup, armazenamento e organização de computadores', 'Mat: funções do 1º e 2º grau, equações e inequações'),
        ('Fís: quantidade de movimento, impulso, torque e equilíbrio', 'Quím: estados da matéria, gases e soluções (concentração e diluição)', 'Est: probabilidade: clássica, geométrica e axiomática'),
        ('Inglês/Espanhol: verbos (EN: tempos verbais, modais, phrasal verbs · ES: verbos e perífrases)', 'Mat: funções exponencial, logarítmica, polinomial e racional', 'Fís: trabalho, energia, potência e gravitação (Kepler)'),
        ('Quím: reações, balanceamento, estequiometria e termoquímica', 'Bio: anatomia e fisiologia humana', 'Info: Windows 11: arquivos, pastas, Painel de Controle e Prompt'),
        ('Est: variáveis aleatórias e distribuições de probabilidade', 'Inglês/Espanhol: estruturas (EN: voz passiva, condicionais, relativas, question tags · ES: acentuação, preposições, conjunções, heterossemânticos)', 'Mat: geometria plana: ângulos, áreas, Tales, semelhança e relações métricas'),
        ('Fís: termologia, calorimetria, gases e termodinâmica', 'Quím: cinética, equilíbrio, Kps, pH, tampão e água', 'Bio: ecologia, biomas, problemas ambientais, saneamento e legislação ambiental'),
        ('Info: Excel e Calc: fórmulas, funções e gráficos', 'Est: regressão linear: ajuste da reta', 'Mat: geometria espacial, escalas, trigonometria e ciclo trigonométrico'),
        ('Fís: eletrostática e eletrodinâmica: Coulomb, Ohm, circuitos e consumo', 'Quím: eletroquímica, corrosão e radioatividade', 'Inglês/Espanhol: questões AOCP'),
        ('Bio: saúde: doenças, Saúde Única, primeiros socorros, IST, drogas e saúde mental', 'Info: Word, Writer, PowerPoint e Impress', 'Est: testes t, F e ANOVA (interpretação) + questões AOCP'),
        ('Mat: geometria analítica, sistemas e noções de estatística', 'Fís: magnetismo, óptica geométrica e ondas', 'Quím: química orgânica e química aplicada (petróleo, polímeros, siderurgia)'),
]
_PORT = ["Interpretação, tipologia e gêneros textuais", "Classes de palavras I", "Classes de palavras II", "Funções do QUE e do SE",
         "Termos da oração", "Coordenação e subordinação", "Pontuação", "Concordância", "Regência e crase", "Colocação pronominal",
         "Ortografia e acentuação", "Coesão e relações semânticas", "Figuras de linguagem, significação e formação de palavras",
         "Variação linguística e interpretação", "Questões AOCP", "Questões AOCP"]

# -----------------------------------------------------------------------------
# NOVO: CONTEÚDO PROGRAMÁTICO COMPLETO DO 2º TENENTE (Edital CBMPE 2026, Anexo II)
# Cada matéria: (bloco, nº de questões, pontos, prioridade, [(item, prioridade), ...]).
# Prioridades: critério do plano (peso no edital, desempate e utilidade para a carreira),
# não estatística oficial da banca. Ajuste no checklist se quiser.
# -----------------------------------------------------------------------------
EDITAL_CFO = {
    "Língua Portuguesa": ("Bloco I", 5, 5, "Alta", [
        ("1. Compreensão e interpretação de textos", "Alta"), ("2. Tipologias e gêneros textuais", "Média"),
        ("3. Figuras de linguagem", "Baixa"), ("4. Relações semânticas entre orações, períodos e parágrafos", "Alta"),
        ("5. Ortografia oficial", "Baixa"), ("6. Acentuação gráfica", "Baixa"), ("7. Emprego das classes de palavras", "Média"),
        ("8. Crase", "Média"), ("9. Sintaxe da oração e do período (coordenação e subordinação)", "Alta"),
        ("10. Funções do QUE e do SE", "Média"), ("11. Mecanismos de coesão textual", "Alta"),
        ("12. Pontuação", "Alta"), ("13. Concordância nominal e verbal", "Alta"), ("14. Regência nominal e verbal", "Média"),
        ("15. Colocação pronominal", "Média"), ("16. Formação de palavras", "Baixa"), ("17. Significação das palavras", "Média"),
        ("18. Variação linguística", "Baixa")]),
    "Língua Estrangeira": ("Bloco I", 5, 5, "Média", [
        ("Inglês — 1. Compreensão e interpretação de gêneros textuais", "Alta"), ("Inglês — 2. Vocabulário aplicado", "Alta"),
        ("Inglês — Substantivos, adjetivos (comparativo e superlativo), advérbios, preposições e artigos", "Baixa"),
        ("Inglês — Pronomes", "Baixa"), ("Inglês — Phrasal verbs", "Média"), ("Inglês — Tempos verbais", "Média"),
        ("Inglês — Verbos modais", "Média"), ("Inglês — Voz ativa e passiva", "Baixa"),
        ("Inglês — Orações adverbiais e condicionais", "Média"), ("Inglês — Orações relativas", "Baixa"),
        ("Inglês — Padrões verbais (infinitivo e gerúndio) e question tags", "Baixa"),
        ("Espanhol — 1. Leitura e compreensão de textos", "Alta"), ("Espanhol — Determinantes do nome (artigos, possessivos, demonstrativos etc.)", "Média"),
        ("Espanhol — Substantivos e adjetivos (gênero, número e grau)", "Baixa"), ("Espanhol — Pronomes", "Média"),
        ("Espanhol — Verbos e perífrases verbais", "Média"), ("Espanhol — Advérbios, preposições e conjunções", "Baixa"),
        ("Espanhol — Acentuação", "Baixa"), ("Espanhol — Sinônimos e antônimos", "Média"),
        ("Espanhol — Heterográficos, heterotônicos, heterogenéricos e heterossemânticos", "Alta")]),
    "Informática": ("Bloco I", 5, 5, "Média", [
        ("1. Internet e intranet", "Média"), ("2. Navegadores, serviços de internet e computação em nuvem", "Média"),
        ("3. Segurança da informação (malwares, phishing, criptografia, autenticação)", "Alta"),
        ("4. Armazenamento de dados e backup", "Média"),
        ("5. Arquivos e pastas; organização de computadores e periféricos", "Média"),
        ("6. Windows 11, Painel de Controle e Prompt de Comando", "Média"),
        ("7a. Word 2019 e Writer", "Média"), ("7b. Excel 2019 e Calc (fórmulas, funções, gráficos)", "Alta"),
        ("7c. PowerPoint 2019 e Impress", "Baixa")]),
    "Estatística": ("Bloco I", 5, 5, "Média", [
        ("1. População, censo, amostra e apresentação de dados", "Média"),
        ("2. Probabilidade: definição clássica, geométrica e axiomática", "Alta"),
        ("3. Variáveis aleatórias e distribuições de probabilidade", "Média"),
        ("4. Medidas de centralidade, posição e dispersão; histograma e boxplot", "Alta"),
        ("5. Testes de hipóteses: t, F e ANOVA", "Baixa"), ("6. Regressão linear", "Média")]),
    "Matemática": ("Bloco II", 5, 5, "Média", [
        ("1a. Conjuntos numéricos, desigualdades, divisibilidade e fatoração", "Média"),
        ("1b. Razões, proporções, porcentagem e juros", "Alta"), ("1c. Sequências e progressões (PA e PG)", "Média"),
        ("1d. Princípios de contagem", "Média"),
        ("2a. Geometria plana: figuras, ângulos, áreas, Tales, semelhança e relações métricas", "Alta"),
        ("2b. Geometria espacial, medidas e escalas", "Média"), ("2c. Trigonometria do ângulo agudo", "Média"),
        ("3. Estatística e probabilidade básicas", "Baixa"),
        ("4a. Funções do 1º e do 2º grau; equações e inequações", "Alta"),
        ("4b. Funções exponencial, logarítmica, polinomial e racional", "Média"),
        ("4c. Ciclo trigonométrico e funções trigonométricas", "Baixa"),
        ("5. Geometria analítica (plano, retas, circunferências) e sistemas", "Média")]),
    "Física": ("Bloco II", 5, 5, "Média", [
        ("1. Grandezas, SI, notação científica e vetores", "Média"), ("2a. Cinemática", "Alta"),
        ("2b. Dinâmica: Leis de Newton, atrito, diagramas e movimento circular", "Alta"),
        ("2c. Quantidade de movimento, impulso, torque e equilíbrio", "Média"),
        ("2d. Hidrostática: Stevin, Pascal e Arquimedes", "Alta"), ("3. Trabalho, energia e potência", "Alta"),
        ("4. Gravitação universal e Leis de Kepler", "Baixa"),
        ("5a. Eletrostática: Coulomb, campo, potencial e capacitores", "Baixa"),
        ("5b. Eletrodinâmica: Ohm, circuitos, potência e consumo", "Média"), ("5c. Magnetismo", "Baixa"),
        ("6a. Óptica geométrica", "Média"), ("6b. Ondas", "Média"),
        ("7. Termologia, calorimetria, gases e termodinâmica", "Alta")]),
    "Química": ("Bloco II", 5, 5, "Média", [
        ("1.1 Substâncias, misturas e separação", "Média"), ("1.2–1.3 Estrutura atômica e tabela periódica", "Média"),
        ("1.4–1.5 Ligações, forças intermoleculares, Lewis e nox", "Média"), ("1.6 Óxidos, ácidos, bases e sais", "Média"),
        ("1.7 Estados da matéria e gases", "Média"), ("1.8 Soluções: concentração, diluição e mistura", "Alta"),
        ("1.9 Radioatividade", "Baixa"), ("2.1 Reações e estequiometria", "Alta"), ("2.2 Termoquímica", "Média"),
        ("2.3 Cinética química", "Média"), ("2.4–2.5 Equilíbrio, Kps, pH, pOH e tampão", "Média"),
        ("2.6 Eletroquímica e corrosão", "Baixa"), ("3. Química orgânica: funções, nomenclatura, isomeria e reações", "Média"),
        ("4. Química aplicada: petróleo, polímeros e siderurgia", "Baixa"),
        ("5. Aspectos químicos do fogo e da combustão", "Alta"),
        ("5. Produtos químicos perigosos e Fichas com Dados de Segurança (FDS)", "Alta"),
        ("6. Água: propriedades e tratamento", "Média")]),
    "Biologia": ("Bloco II", 5, 5, "Média", [
        ("1a. Citologia e metabolismo energético", "Média"),
        ("1b. Genética, síntese proteica, biotecnologia e ética", "Média"),
        ("2a. Evolução e classificação dos seres vivos", "Baixa"),
        ("2b. Embriologia, anatomia e fisiologia humana", "Alta"),
        ("3a. Ecologia: ecossistemas, populações, cadeias e ciclos", "Média"),
        ("3b. Biomas, problemas ambientais, conservação, saneamento e legislação ambiental", "Média"),
        ("4. Saúde: doenças, Saúde Única, primeiros socorros, IST, drogas e saúde mental", "Alta")]),
    "Direito Constitucional": ("Bloco III", 8, 8, "Alta", [
        ("1–2. Constituição: conceito, classificação, histórico, elementos e estrutura", "Baixa"),
        ("3. Poder constituinte, mutação, recepção e repristinação", "Média"),
        ("4. Eficácia e aplicabilidade das normas", "Média"), ("5. Controle de constitucionalidade", "Média"),
        ("6a. Direitos e deveres individuais e coletivos (art. 5º)", "Alta"), ("6b. Remédios constitucionais", "Alta"),
        ("6c. Direitos sociais", "Média"), ("6d. Nacionalidade", "Média"), ("6e. Direitos políticos e partidos", "Média"),
        ("7a. Organização do Estado: federação, entes e competências", "Alta"),
        ("7b. Administração Pública e servidores (arts. 37 a 42)", "Alta"),
        ("8a. Poder Legislativo", "Média"), ("8b. Poder Executivo", "Média"), ("8c. Poder Judiciário", "Média"),
        ("9. Funções essenciais à Justiça", "Baixa"),
        ("10. Defesa do Estado: estados de defesa e de sítio, Forças Armadas e segurança pública (art. 144)", "Alta"),
        ("11. Ordem social", "Baixa"), ("12. Constituição do Estado de Pernambuco", "Média"),
        ("13. Súmulas e jurisprudência dos tribunais superiores", "Média"), ("14. ECA (Lei 8.069/1990)", "Média"),
        ("15. Estatuto da Juventude (Lei 12.852/2013)", "Baixa"), ("16. Lei Maria da Penha (Lei 11.340/2006)", "Média")]),
    "Direito Administrativo": ("Bloco III", 7, 7, "Alta", [
        ("1. Estado, governo e administração pública", "Baixa"), ("2. Conceito, fontes e princípios", "Alta"),
        ("3. Organização administrativa: direta e indireta", "Média"), ("4. Agentes públicos", "Alta"),
        ("5. Poderes administrativos e abuso de poder", "Alta"), ("6. Ato administrativo", "Alta"),
        ("7. Serviços públicos e delegação", "Média"), ("8a. Controle da administração", "Média"),
        ("8b. Responsabilidade civil do Estado", "Alta")]),
    "Direito Penal Militar": ("Bloco III", 5, 5, "Alta", [
        ("1. Aplicação da lei penal militar", "Alta"), ("2. Do crime (inclui art. 9º do CPM)", "Alta"),
        ("3. Imputabilidade penal", "Média"), ("4. Concurso de agentes", "Média"), ("5. Das penas", "Média"),
        ("6. Medidas de segurança", "Baixa"), ("7. Ação penal", "Baixa"), ("8. Extinção da punibilidade", "Média"),
        ("9. Crimes militares em tempo de paz", "Alta"), ("10. Crimes militares em tempo de guerra", "Baixa"),
        ("11. Súmulas e jurisprudência", "Média")]),
    "Legislação dos Militares de PE": ("Bloco III", 10, 10, "Alta", [
        ("Lei 11.817/2000 — Regime disciplinar", "Alta"), ("Lei 11.817/2000 — Transgressões disciplinares", "Alta"),
        ("Lei 11.817/2000 — Penas disciplinares e medidas administrativas", "Alta"),
        ("Lei 11.817/2000 — Recursos e comissões recursais", "Média"),
        ("Lei 11.817/2000 — Cancelamento de penas e recompensas", "Média"),
        ("Lei 11.817/2000 — Transgressões em espécie", "Média"), ("Decreto 50.014/2020", "Média"),
        ("Lei 6.783/1974 — Hierarquia e disciplina", "Alta"), ("Lei 6.783/1974 — Cargo e função", "Média"),
        ("Lei 6.783/1974 — Obrigações e deveres", "Alta"),
        ("Lei 6.783/1974 — Direitos, prerrogativas e sistema de proteção social", "Alta"),
        ("Lei 6.783/1974 — Situações especiais", "Média"), ("Lei 6.783/1974 — Desligamento ou exclusão", "Alta"),
        ("Lei 6.783/1974 — Tempo de serviço", "Média"),
        ("Lei 15.187/2013 — Generalidades e organização básica do CBMPE", "Média"),
        ("Lei 15.187/2013 — Atribuições funcionais e orgânicas e pessoal", "Média"),
        ("Lei 14.751/2023 — Disposições gerais, princípios e competências", "Alta"),
        ("Lei 14.751/2023 — Organização, efetivos, hierarquia, ingresso e quadros", "Alta"),
        ("Lei 14.751/2023 — Garantias, vedações, direitos e disposições finais", "Alta")]),
    "Redação": ("Redação", 0, 30, "Alta", []),
}
PONTOS_POR_BLOCO = {"Bloco I": 20, "Bloco II": 20, "Bloco III": 30}

def edital_cfo_formato_app():
    """O mesmo edital no formato que a tela '🧭 Planejar Estudos' entende."""
    materias = []
    for nome, (bloco, questoes, pontos, prio, itens) in EDITAL_CFO.items():
        m = {"nome": nome, "bloco": bloco, "questoes": questoes, "pontos": pontos, "prioridade": prio,
             "tipo": "redacao" if nome == "Redação" else "", "conhecimento": 3,
             "topicos": [{"nome": i, "prioridade": p} for i, p in itens]}
        materias.append(m)
    return {"objetivo": CRONO_META_NOME, "tipo": "Concurso", "data_prova": "2027-02-28",
            "banca": "Instituto AOCP", "materias": materias}

def garantir_itens_edital(conn, objetivo, edital):
    """Cria no checklist os itens que ainda não existem (não mexe no que você já marcou)."""
    c = conn.cursor()
    for m in edital["materias"]:
        for ordem, t in enumerate(m.get("topicos", []), start=1):
            c.execute("""INSERT OR IGNORE INTO edital_itens (objetivo, materia, ordem, item, prioridade)
                         VALUES (?, ?, ?, ?, ?)""", (objetivo, m["nome"], ordem, t["nome"], t.get("prioridade", "Média")))
    conn.commit()

@st.cache_resource
def preparar_edital_cfo_uma_vez():
    conn = get_db()
    edital = edital_cfo_formato_app()
    garantir_itens_edital(conn, CRONO_META_NOME, edital)
    c = conn.cursor()
    c.execute("SELECT id FROM editais WHERE nome = ?", (CRONO_META_NOME,))
    if c.fetchone() is None:
        c.execute("INSERT INTO editais (nome, conteudo, ajustes) VALUES (?, ?, ?)",
                  (CRONO_META_NOME, json.dumps(edital, ensure_ascii=False), "{}"))
        conn.commit()
    # Traz as questões que você já tinha registrado no formato antigo (uma vez só)
    c.execute("SELECT valor FROM configuracoes WHERE chave = 'migrou_exercicios'")
    if c.fetchone() is None:
        c.execute("""INSERT INTO questoes (data, objetivo, materia, item_id, total, acertos, fonte, obs)
                     SELECT e.data, me.nome, m.nome, NULL, e.acertos + e.erros, e.acertos, 'Registro antigo', t.nome
                     FROM exercicios e JOIN topicos t ON e.topico_id = t.id
                     JOIN materias m ON t.materia_id = m.id JOIN metas me ON m.meta_id = me.id""")
        c.execute("INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES ('migrou_exercicios', '1')")
        conn.commit()
    conn.close()
    return True

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
    add(17, 4, 1, "Simulado", 240, SIM, "Simulado 1: 70 questões em 3 h + redação em 1 h")
    add(19, 4, 1, "Simulado", 240, SIM, "Simulado 2: 70 questões em 3 h + redação em 1 h")
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
                grupos.append("; ".join(atual))
                atual, acum = [], 0.0
    if atual:
        grupos.append("; ".join(atual))
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
    garantir_itens_edital(conn, edital["objetivo"], edital)  # NOVO: os tópicos do edital entram no checklist

def total_semanas(meta_id, conn):
    c = conn.cursor()
    c.execute("""SELECT MAX(t.semana) FROM topicos t JOIN materias m ON t.materia_id = m.id
                 WHERE m.meta_id = ?""", (int(meta_id),))
    res = c.fetchone()[0]
    return int(res) if res else 0

def semana_e_dia_de_hoje(meta_id):
    """Devolve (semana, dia) de hoje no cronograma. dia = 0..6 (5 e 6 = fim de semana)."""
    inicio = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id}", CRONO_INICIO.isoformat()))
    d_hoje = hoje()
    return (d_hoje - inicio).days // 7 + 1, d_hoje.weekday()

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
        c.execute("UPDATE topicos SET status = ?, teoria = ?, resumo = MAX(resumo, ?), minutos_estudados = ? WHERE id = ?",
                  (status, teoria, resumo, int(minutos), int(topico_id)))
    conn.commit()

# -----------------------------------------------------------------------------
# NOVO: CHECKLIST DO EDITAL, REVISÕES ESPAÇADAS E ESTATÍSTICAS DE QUESTÕES
# -----------------------------------------------------------------------------
INTERVALOS_REVISAO = [1, 7, 30, 60]  # dias: 1ª revisão no dia seguinte, depois 7, 30 e a cada 60

# NOVO: cada revisão tem um método e um tempo próprios.
# A posição na lista = quantas revisões o item já teve (0 = a primeira revisão, 1 dia depois de estudar).
ETAPAS_REVISAO = [
    {"nome": "1ª revisão (24 horas)", "minutos": 15, "faixa": "10 a 15 min", "metodo": [
        "Sem olhar o material, escreva numa folha os pontos principais do item (o que lembrar).",
        "Confira com o seu resumo ou o PDF e complete com outra cor o que faltou: isso é o que você precisa fixar.",
        "Transforme o que faltou em 3 a 5 flashcards (pergunta de um lado, resposta do outro)."]},
    {"nome": "2ª revisão (7 dias)", "minutos": 20, "faixa": "15 a 20 min", "metodo": [
        "Faça os flashcards do item antes de qualquer leitura.",
        "Resolva 10 questões só deste item e registre em '📝 Registrar Questões'.",
        "Releia apenas o trecho da teoria ligado às questões que errou e anote o erro no caderno de erros."]},
    {"nome": "3ª revisão (30 dias)", "minutos": 25, "faixa": "20 a 25 min", "metodo": [
        "Refaça de memória o mapa mental ou o esquema do item; só depois compare com o original.",
        "Leia a lei seca ou as definições do trecho, grifando o que costuma cair (prazos, competências, exceções).",
        "Resolva 10 questões misturando este item com outros da mesma matéria."]},
    {"nome": "Revisão de manutenção (a cada 60 dias)", "minutos": 10, "faixa": "cerca de 10 min", "metodo": [
        "Passe os flashcards do item.",
        "Faça 5 questões. Se errar 2 ou mais, marque \"Esqueci\": o item volta ao início das revisões."]},
]
RESULTADOS_REVISAO = {"bem": "😀 Lembrei bem", "medio": "😐 Mais ou menos", "esqueci": "😟 Esqueci"}

def etapa_revisao(n_revisoes):
    return ETAPAS_REVISAO[min(int(n_revisoes or 0), len(ETAPAS_REVISAO) - 1)]
FATOR_PRIO_ITEM = {"Alta": 1.5, "Média": 1.0, "Baixa": 0.65}
STATUS_BLOCO = ["Pendente", "Parcial", "Concluído", "Adiado"]
FONTES_QUESTOES = ["Estratégia (PDF/curso)", "Banco de questões (QConcursos, TEC etc.)", "Prova anterior AOCP",
                   "Simulado", "Apostila / material próprio", "Outro"]
MOTIVOS_ERRO = {
    "erro_conteudo": ("Não sabia o conteúdo",
                      "Volte à teoria do item (aula do PDF), faça um resumo curto e resolva 10 questões só desse item em até 48 horas."),
    "erro_interpretacao": ("Confundi / interpretei errado",
                           "Releia a regra exata (lei seca ou definição) e monte um quadro comparando os institutos parecidos. "
                           "No enunciado, grife palavras como \"exceto\", \"salvo\", \"somente\" e \"não\"."),
    "erro_atencao": ("Falta de atenção",
                     "Leia o comando duas vezes antes das alternativas, marque as palavras-chave e copie o erro para o caderno de erros."),
    "erro_tempo": ("Tempo / chute",
                   "Treine blocos cronometrados. A prova tem 5 horas para 70 questões e a redação: deixando 1 hora para a redação, "
                   "sobram cerca de 3 minutos e meio por questão."),
}

def idioma_escolhido():
    return get_config("idioma_prova", "Inglês")

def filtrar_idioma(df, col_materia="materia", col_item="item"):
    """Esconde os itens da língua estrangeira que você não escolheu."""
    if df.empty:
        return df
    outro = "Espanhol" if idioma_escolhido() == "Inglês" else "Inglês"
    mascara = (df[col_materia] == "Língua Estrangeira") & df[col_item].astype(str).str.startswith(outro + " —")
    return df[~mascara]

def marcar_teoria_itens(conn, ids):
    c = conn.cursor()
    d = hoje()
    for i in ids:
        c.execute("SELECT teoria FROM edital_itens WHERE id = ?", (int(i),))
        r = c.fetchone()
        if r is not None and not r[0]:
            c.execute("""UPDATE edital_itens SET teoria = 1, data_teoria = ?, n_revisoes = 0, proxima_revisao = ?
                         WHERE id = ?""", (d.isoformat(), (d + datetime.timedelta(days=INTERVALOS_REVISAO[0])).isoformat(), int(i)))
    conn.commit()

def desmarcar_teoria_item(conn, item_id):
    conn.execute("""UPDATE edital_itens SET teoria = 0, data_teoria = NULL, n_revisoes = 0, proxima_revisao = NULL
                    WHERE id = ?""", (int(item_id),))
    conn.commit()

def acerto_do_item(conn, item_id):
    """(% de acerto, nº de questões) do item, ou (None, 0) se ainda não há questões."""
    r = conn.execute("SELECT COALESCE(SUM(total), 0), COALESCE(SUM(acertos), 0) FROM questoes WHERE item_id = ?",
                     (int(item_id),)).fetchone()
    return (100.0 * r[1] / r[0], int(r[0])) if r[0] else (None, 0)

def registrar_revisao(conn, item_id, resultado="bem"):
    """Agenda a próxima revisão conforme o quanto você lembrou e o seu acerto nas questões do item.
    - Lembrei bem: avança para a próxima etapa (7, 30 e depois 60 dias).
    - Mais ou menos: avança, mas com metade do intervalo.
    - Esqueci: repete a mesma etapa daqui a 2 dias (e, se já estava na manutenção, recomeça do início)."""
    c = conn.cursor()
    c.execute("SELECT n_revisoes FROM edital_itens WHERE id = ?", (int(item_id),))
    n_atual = int(c.fetchone()[0] or 0)
    if resultado == "esqueci":
        n_novo = 0 if n_atual >= len(ETAPAS_REVISAO) - 1 else n_atual
        intervalo = 2
    else:
        n_novo = n_atual + 1
        intervalo = INTERVALOS_REVISAO[min(n_novo, len(INTERVALOS_REVISAO) - 1)]
        if resultado == "medio":
            intervalo = max(2, round(intervalo / 2))
    taxa, qtd = acerto_do_item(conn, item_id)
    if resultado != "esqueci" and taxa is not None and qtd >= 5 and taxa < 60:
        intervalo = max(2, round(intervalo / 2))  # acerto baixo nas questões: revisa mais cedo
    proxima = hoje() + datetime.timedelta(days=intervalo)
    c.execute("UPDATE edital_itens SET n_revisoes = ?, proxima_revisao = ? WHERE id = ?",
              (n_novo, proxima.isoformat(), int(item_id)))
    c.execute("INSERT INTO revisoes_log (data, item_id, etapa, resultado, proxima) VALUES (?, ?, ?, ?, ?)",
              (hoje().isoformat(), int(item_id), n_atual, resultado, proxima.isoformat()))
    conn.commit()
    return proxima

def objetivos_com_edital(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT objetivo FROM edital_itens ORDER BY objetivo").fetchall()]

def carregar_questoes(conn, objetivo, desde=None):
    sql = """SELECT q.id, q.data, q.materia, q.item_id, COALESCE(i.item, '(sem item específico)') as item,
                    COALESCE(i.prioridade, 'Média') as prioridade, q.total, q.acertos, q.fonte,
                    q.erro_conteudo, q.erro_interpretacao, q.erro_atencao, q.erro_tempo, q.obs
             FROM questoes q LEFT JOIN edital_itens i ON q.item_id = i.id
             WHERE q.objetivo = ?"""
    params = [objetivo]
    if desde is not None:
        sql += " AND q.data >= ?"
        params.append(desde.isoformat())
    df = pd.read_sql_query(sql + " ORDER BY q.data, q.id", conn, params=params)
    if not df.empty:
        df["erros"] = df["total"] - df["acertos"]
    return df

def pct(acertos, total):
    return round(100.0 * acertos / total, 1) if total else None

def data_do_bloco(inicio, semana, dia):
    return inicio + datetime.timedelta(weeks=int(semana) - 1, days=int(dia))

def prioridade_da_materia(nome):
    return EDITAL_CFO[nome][3] if nome in EDITAL_CFO else "Média"

# -----------------------------------------------------------------------------
# NOVO: CRONÔMETRO DE TEMPO LÍQUIDO (Iniciar / Pausar / Finalizar)
# Conta para cima; as pausas não entram. O estado fica no banco (e na nuvem),
# então o tempo continua certo mesmo se a tela do celular apagar ou a página recarregar.
# -----------------------------------------------------------------------------
LIMITE_SEM_PAUSA_SEG = 4 * 3600  # aviso: mais de 4 h seguidas sem pausar

def fmt_hms(seg):
    seg = max(0, int(seg))
    return f"{seg // 3600:02d}:{(seg % 3600) // 60:02d}:{seg % 60:02d}"

def fmt_horas(minutos):
    minutos = int(minutos or 0)
    return f"{minutos // 60}h{minutos % 60:02d}" if minutos >= 60 else f"{minutos} min"

def cron_estado(conn, topico_id):
    r = conn.execute("SELECT status, inicio_trecho, acumulado, pausas FROM cronometro_bloco WHERE topico_id = ?",
                     (int(topico_id),)).fetchone()
    if not r:
        return {"status": "PARADO", "segundos": 0, "pausas": 0, "trecho": 0}
    status, inicio, acumulado, pausas = r
    trecho = max(0.0, time.time() - inicio) if status == "RODANDO" and inicio else 0.0
    return {"status": status, "segundos": int((acumulado or 0) + trecho), "pausas": int(pausas or 0), "trecho": int(trecho)}

def cron_pausar(conn, topico_id, contar_pausa=True):
    est = cron_estado(conn, topico_id)
    if est["status"] != "RODANDO":
        return
    conn.execute("UPDATE cronometro_bloco SET status = 'PAUSADO', inicio_trecho = NULL, acumulado = ?, pausas = pausas + ? "
                 "WHERE topico_id = ?", (est["segundos"], 1 if contar_pausa else 0, int(topico_id)))
    conn.commit()

def cron_iniciar(conn, topico_id):
    # Só um cronômetro rodando por vez: se outro bloco estava rodando, ele é pausado.
    for (outro,) in conn.execute("SELECT topico_id FROM cronometro_bloco WHERE status = 'RODANDO' AND topico_id != ?",
                                 (int(topico_id),)).fetchall():
        cron_pausar(conn, outro)
    est = cron_estado(conn, topico_id)
    if est["status"] == "RODANDO":
        return
    if est["status"] == "PARADO":
        conn.execute("INSERT OR REPLACE INTO cronometro_bloco (topico_id, status, inicio_trecho, acumulado, pausas, iniciado_em) "
                     "VALUES (?, 'RODANDO', ?, 0, 0, ?)", (int(topico_id), time.time(), agora().isoformat(timespec="minutes")))
    else:
        conn.execute("UPDATE cronometro_bloco SET status = 'RODANDO', inicio_trecho = ? WHERE topico_id = ?",
                     (time.time(), int(topico_id)))
    conn.commit()

def cron_descartar(conn, topico_id):
    conn.execute("DELETE FROM cronometro_bloco WHERE topico_id = ?", (int(topico_id),))
    conn.commit()

def registrar_sessao(conn, objetivo, materia, topico_id, minutos, pausas=0, inicio=None, origem="cronômetro"):
    if int(minutos) <= 0:
        return
    conn.execute("""INSERT INTO sessoes_estudo (data, objetivo, materia, topico_id, minutos, pausas, inicio, fim, origem)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (hoje().isoformat(), objetivo, materia, int(topico_id), int(minutos), int(pausas), inicio,
                  agora().isoformat(timespec="minutes"), origem))
    conn.commit()

def tempo_estudado(conn, objetivo):
    """Minutos líquidos estudados hoje e nesta semana (segunda a domingo)."""
    d = hoje()
    seg = d - datetime.timedelta(days=d.weekday())
    m_hoje = conn.execute("SELECT COALESCE(SUM(minutos), 0) FROM sessoes_estudo WHERE objetivo = ? AND data = ?",
                          (objetivo, d.isoformat())).fetchone()[0]
    m_sem = conn.execute("SELECT COALESCE(SUM(minutos), 0) FROM sessoes_estudo WHERE objetivo = ? AND data >= ? AND data <= ?",
                         (objetivo, seg.isoformat(), d.isoformat())).fetchone()[0]
    return int(m_hoje), int(m_sem)

def _relogio_bloco(topico_id, minutos_plan):
    """Mostrador do cronômetro. Quando está rodando, só este pedaço da tela se atualiza a cada segundo."""
    con = get_db()
    est = cron_estado(con, topico_id)
    con.close()
    seg, meta = est["segundos"], minutos_plan * 60
    st.markdown(f"### ⏱️ `{fmt_hms(seg)}`")
    st.markdown("🟢 **Estudando** · o tempo está contando" if est["status"] == "RODANDO"
                else "⏸️ **Pausado** · o tempo parado não conta")
    if meta > 0:
        st.progress(min(1.0, seg / meta))
        if seg >= meta:
            st.success(f"🔔 Tempo previsto atingido! Você já está {fmt_hms(seg - meta)} além dos {minutos_plan} min. "
                       "Pode continuar: o tempo extra também é registrado.")
        else:
            st.caption(f"Previsto: {minutos_plan} min · faltam {fmt_hms(meta - seg)} · pausas: {est['pausas']} (não contam)")
    if est["status"] == "RODANDO" and est["trecho"] > LIMITE_SEM_PAUSA_SEG:
        st.warning("⚠️ O cronômetro está rodando há mais de 4 horas sem pausa. Se esqueceu ligado, "
                   "toque em ⏹️ Finalizar e corrija os minutos antes de salvar.")

def finalizar_bloco(conn, row, objetivo, status, minutos, itens_ids, prefixo):
    topico_id = int(row['id'])
    est = cron_estado(conn, topico_id)
    inicio = conn.execute("SELECT iniciado_em FROM cronometro_bloco WHERE topico_id = ?", (topico_id,)).fetchone()
    salvar_status_topico(conn, topico_id, status, int(row['minutos_estudados'] or 0) + int(minutos))
    marcar_teoria_itens(conn, itens_ids)
    registrar_sessao(conn, objetivo, row['materia'], topico_id, minutos, est["pausas"], inicio[0] if inicio else None)
    cron_descartar(conn, topico_id)
    st.session_state.pop(f"{prefixo}_fin_{topico_id}", None)
    st.toast(f"Registrado: {fmt_horas(minutos)} de estudo líquido.")

def mostrar_bloco(conn, row, objetivo, prefixo, data_bloco=None):
    """Mostra um bloco do cronograma com o cronômetro de tempo líquido (Iniciar / Pausar / Finalizar)."""
    topico_id = int(row['id'])
    minutos_plan = int(row['minutos_planejados'] or 0)
    icones = {"Concluído": "✅", "Parcial": "⏳", "Adiado": "📌"}
    icone = icones.get(row['status'], "📖")
    quando = f" · de {DIAS_SEMANA[data_bloco.weekday()][:3]} {data_bloco:%d/%m}" if data_bloco is not None else ""
    est = cron_estado(conn, topico_id)
    chave_fin = f"{prefixo}_fin_{topico_id}"
    ativo = est["status"] != "PARADO"
    aberto = row['status'] != "Concluído" or ativo
    with st.expander(f"{icone} **{row['bloco']} · {row['materia']}** | {minutos_plan} min{quando}", expanded=aberto):
        st.markdown(f"**Conteúdo:** {row['nome'].split(' · ', 1)[-1]}")
        st.write(f"**Status:** `{row['status']}` · **Minutos registrados:** {int(row['minutos_estudados'] or 0)}")

        finalizando = ativo and st.session_state.get(chave_fin, False)
        if not ativo:
            st.caption("⏱️ Toque em **▶️ Iniciar** quando começar. Se precisar parar, use **⏸️ Pausar**; "
                       "no fim, **⏹️ Finalizar**. Só o tempo líquido (sem as pausas) vai para as estatísticas.")
            if st.button("▶️ Iniciar", key=f"{prefixo}_start_{topico_id}", type="primary"):
                cron_iniciar(conn, topico_id)
                st.rerun()
        else:
            if est["status"] == "RODANDO":
                st.fragment(run_every=1)(_relogio_bloco)(topico_id, minutos_plan)
            else:
                _relogio_bloco(topico_id, minutos_plan)
            if not finalizando:
                c1, c2 = st.columns(2)
                with c1:
                    if est["status"] == "RODANDO":
                        if st.button("⏸️ Pausar", key=f"{prefixo}_pause_{topico_id}"):
                            cron_pausar(conn, topico_id)
                            st.rerun()
                    else:
                        if st.button("▶️ Continuar", key=f"{prefixo}_start_{topico_id}", type="primary"):
                            cron_iniciar(conn, topico_id)
                            st.rerun()
                with c2:
                    if st.button("⏹️ Finalizar", key=f"{prefixo}_stop_{topico_id}"):
                        cron_pausar(conn, topico_id, contar_pausa=False)
                        st.session_state[chave_fin] = True
                        st.rerun()

        # Itens do edital desta matéria: o que você marcar aqui entra no checklist e nas revisões
        itens_ids = []
        df_itens = pd.read_sql_query("""SELECT id, item, teoria FROM edital_itens WHERE objetivo = ? AND materia = ?
                                        ORDER BY teoria, ordem""", conn, params=(objetivo, row['materia']))
        df_itens = filtrar_idioma(df_itens.assign(materia=row['materia']))
        if not df_itens.empty:
            pendentes = df_itens[df_itens['teoria'] == 0]
            if not pendentes.empty:
                st.caption(f"📚 Próximo item do edital ainda não estudado: **{pendentes.iloc[0]['item']}**")
            rotulos = {int(r['id']): ("✔ " if r['teoria'] else "") + r['item'] for _, r in df_itens.iterrows()}
            itens_ids = st.multiselect("Itens do edital que você estudou neste bloco (opcional):", list(rotulos.keys()),
                                       format_func=lambda i: rotulos[i], key=f"{prefixo}_itens_{topico_id}",
                                       placeholder="Escolha os itens do edital")

        minutos_ja = int(row['minutos_estudados'] or 0)
        if finalizando:
            seg = est["segundos"]
            liquido = min(600, round(seg / 60))
            with st.container(border=True):
                st.markdown(f"**⏹️ Cronômetro parado.** Tempo líquido: **{fmt_hms(seg)}** "
                            f"({est['pausas']} pausa(s), que não contam).")
                minutos = st.number_input("Minutos que vão para as estatísticas (corrija se esqueceu o cronômetro ligado):",
                                          min_value=0, max_value=600, value=int(liquido), step=1,
                                          key=f"{prefixo}_min_{topico_id}")
                st.write("Como foi o bloco?")
                f1, f2 = st.columns(2)
                with f1:
                    if st.button("✅ Concluí o bloco", key=f"{prefixo}_conc_{topico_id}", type="primary"):
                        finalizar_bloco(conn, row, objetivo, "Concluído", minutos, itens_ids, prefixo)
                        st.rerun()
                with f2:
                    if st.button("⏳ Fiz só uma parte", key=f"{prefixo}_parc_{topico_id}"):
                        finalizar_bloco(conn, row, objetivo, "Parcial", minutos, itens_ids, prefixo)
                        st.rerun()
                g1, g2 = st.columns(2)
                with g1:
                    if st.button("↩️ Voltar a estudar", key=f"{prefixo}_volta_{topico_id}"):
                        st.session_state.pop(chave_fin, None)
                        cron_iniciar(conn, topico_id)
                        st.rerun()
                with g2:
                    if st.checkbox("Quero descartar este tempo", key=f"{prefixo}_confdesc_{topico_id}"):
                        if st.button("🗑️ Descartar", key=f"{prefixo}_desc_{topico_id}"):
                            cron_descartar(conn, topico_id)
                            st.session_state.pop(chave_fin, None)
                            st.rerun()
        elif ativo:
            st.caption("Quando terminar, toque em **⏹️ Finalizar** para registrar o tempo e dizer como foi o bloco.")
        else:
            st.caption("Estudou sem o cronômetro? Use os botões abaixo: o app registra o tempo previsto do bloco.")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅ Concluí este bloco", key=f"{prefixo}_conc_{topico_id}"):
                    minutos = minutos_ja if minutos_ja > 0 else minutos_plan
                    salvar_status_topico(conn, topico_id, "Concluído", minutos)
                    marcar_teoria_itens(conn, itens_ids)
                    registrar_sessao(conn, objetivo, row['materia'], topico_id, minutos - minutos_ja, origem="manual")
                    st.rerun()
            with col_b:
                if st.button("⏳ Fiz só uma parte", key=f"{prefixo}_parc_{topico_id}"):
                    salvar_status_topico(conn, topico_id, "Parcial", minutos_ja)
                    marcar_teoria_itens(conn, itens_ids)
                    st.rerun()
    return False

ID_CRONO_REVISOES = -1          # o cronômetro da sessão de revisões usa este número no lugar de um bloco
MATERIA_REVISOES = "🔁 Revisões"

def mostrar_cronometro_revisoes(conn, objetivo, minutos_previstos):
    """Um cronômetro só para a sessão de revisões do dia (Iniciar / Pausar / Finalizar)."""
    est = cron_estado(conn, ID_CRONO_REVISOES)
    chave_fin = "rev_crono_fin"
    ativo = est["status"] != "PARADO"
    with st.container(border=True):
        if not ativo:
            st.caption("⏱️ Toque em **▶️ Iniciar revisões** antes da primeira e faça todas com o cronômetro rodando. "
                       "Continue marcando cada item pelo resultado. No fim, **⏹️ Finalizar**.")
            if st.button("▶️ Iniciar revisões", key="rev_crono_start", type="primary"):
                cron_iniciar(conn, ID_CRONO_REVISOES)
                st.rerun()
            return
        if est["status"] == "RODANDO":
            st.fragment(run_every=1)(_relogio_bloco)(ID_CRONO_REVISOES, minutos_previstos)
        else:
            _relogio_bloco(ID_CRONO_REVISOES, minutos_previstos)
        if not st.session_state.get(chave_fin, False):
            c1, c2 = st.columns(2)
            with c1:
                if est["status"] == "RODANDO":
                    if st.button("⏸️ Pausar", key="rev_crono_pause"):
                        cron_pausar(conn, ID_CRONO_REVISOES)
                        st.rerun()
                elif st.button("▶️ Continuar", key="rev_crono_start", type="primary"):
                    cron_iniciar(conn, ID_CRONO_REVISOES)
                    st.rerun()
            with c2:
                if st.button("⏹️ Finalizar", key="rev_crono_stop"):
                    cron_pausar(conn, ID_CRONO_REVISOES, contar_pausa=False)
                    st.session_state[chave_fin] = True
                    st.rerun()
            return
        seg = est["segundos"]
        st.markdown(f"**⏹️ Revisões encerradas.** Tempo líquido: **{fmt_hms(seg)}** ({est['pausas']} pausa(s), que não contam).")
        minutos = st.number_input("Minutos que vão para as estatísticas (corrija se esqueceu o cronômetro ligado):",
                                  min_value=0, max_value=600, value=int(min(600, round(seg / 60))), step=1,
                                  key="rev_crono_min")
        f1, f2 = st.columns(2)
        with f1:
            if st.button("💾 Salvar o tempo", key="rev_crono_salvar", type="primary"):
                inicio = conn.execute("SELECT iniciado_em FROM cronometro_bloco WHERE topico_id = ?",
                                      (ID_CRONO_REVISOES,)).fetchone()
                registrar_sessao(conn, objetivo, MATERIA_REVISOES, ID_CRONO_REVISOES, minutos, est["pausas"],
                                 inicio[0] if inicio else None, origem="revisões")
                cron_descartar(conn, ID_CRONO_REVISOES)
                st.session_state.pop(chave_fin, None)
                st.toast(f"Registrado: {fmt_horas(minutos)} de revisão.")
                st.rerun()
        with f2:
            if st.button("↩️ Voltar a revisar", key="rev_crono_volta"):
                st.session_state.pop(chave_fin, None)
                cron_iniciar(conn, ID_CRONO_REVISOES)
                st.rerun()
        if st.checkbox("Quero descartar este tempo", key="rev_crono_confdesc"):
            if st.button("🗑️ Descartar", key="rev_crono_desc"):
                cron_descartar(conn, ID_CRONO_REVISOES)
                st.session_state.pop(chave_fin, None)
                st.rerun()

def mostrar_revisoes_do_dia(conn, objetivo, fim_de_semana=False):
    df = pd.read_sql_query("""SELECT id, materia, item, prioridade, n_revisoes, proxima_revisao FROM edital_itens
                              WHERE objetivo = ? AND teoria = 1 AND proxima_revisao <= ?""",
                           conn, params=(objetivo, hoje().isoformat()))
    df = filtrar_idioma(df)
    if df.empty:
        if cron_estado(conn, ID_CRONO_REVISOES)["status"] != "PARADO":
            st.subheader("🔁 Revisões de hoje: todas feitas ✅")
            mostrar_cronometro_revisoes(conn, objetivo, 0)
            st.markdown("---")
        return
    # Ordem: mais atrasadas primeiro; no empate, maior prioridade
    df["ordem_prio"] = df["prioridade"].map({"Alta": 0, "Média": 1, "Baixa": 2}).fillna(1)
    df = df.sort_values(["proxima_revisao", "ordem_prio"])
    df["min"] = df["n_revisoes"].apply(lambda n: etapa_revisao(n)["minutos"])
    limite = int(get_config("minutos_revisao_fds" if fim_de_semana else "minutos_revisao_dia", "60" if fim_de_semana else "30"))
    df["acumulado"] = df["min"].cumsum()
    cabem = df[(df["acumulado"] <= limite) | (df.index == df.index[0])]
    sobram = df.drop(cabem.index)

    st.subheader(f"🔁 Revisões de hoje: {len(cabem)} itens · cerca de {int(cabem['min'].sum())} min")
    st.caption(f"Seu tempo de revisão {'no fim de semana' if fim_de_semana else 'por dia'} é de {limite} min "
               "(altere em '⚙️ Gerenciador' → '⚙️ Disp. de Tempo'). As mais atrasadas e as de maior prioridade vêm primeiro. "
               "No fim de cada revisão, diga o quanto você lembrou: o app ajusta a próxima data.")
    mostrar_cronometro_revisoes(conn, objetivo, int(cabem['min'].sum()))
    for _, r in cabem.iterrows():
        etapa = etapa_revisao(r["n_revisoes"])
        data_prev = datetime.date.fromisoformat(r["proxima_revisao"])
        atraso = (hoje() - data_prev).days
        with st.container(border=True):
            st.markdown(f"**{r['materia']}** · {r['item']}  \n"
                        f"<small>{etapa['nome']} · ⏱️ {etapa['faixa']}"
                        + (f" · ⚠️ atrasada {atraso} dia(s)" if atraso > 0 else "") + "</small>", unsafe_allow_html=True)
            taxa, qtd = acerto_do_item(conn, r["id"])
            if taxa is not None and qtd >= 5:
                st.caption(f"Seu acerto nas questões deste item: {taxa:.0f}% em {qtd} questões"
                           + (" — abaixo de 60%, a próxima revisão virá mais cedo." if taxa < 60 else "."))
            with st.popover("📋 Como fazer esta revisão"):
                for i, passo in enumerate(etapa["metodo"], start=1):
                    st.markdown(f"{i}. {passo}")
            b1, b2, b3 = st.columns(3)
            for col, chave in zip((b1, b2, b3), RESULTADOS_REVISAO):
                if col.button(RESULTADOS_REVISAO[chave], key=f"rev_{chave}_{r['id']}"):
                    proxima = registrar_revisao(conn, r["id"], chave)
                    st.toast(f"Próxima revisão deste item: {proxima:%d/%m}")
                    st.rerun()
    if not sobram.empty:
        st.caption(f"Ficaram para depois {len(sobram)} revisões (cerca de {int(sobram['min'].sum())} min), por falta de tempo hoje. "
                   "Elas continuam na fila e aparecem primeiro nos próximos dias e no fim de semana.")
        if st.toggle("Tenho mais tempo hoje: mostrar as que ficaram para depois", key="rev_extra"):
            for _, r in sobram.iterrows():
                etapa = etapa_revisao(r["n_revisoes"])
                with st.container(border=True):
                    st.markdown(f"**{r['materia']}** · {r['item']}  \n<small>{etapa['nome']} · ⏱️ {etapa['faixa']}</small>",
                                unsafe_allow_html=True)
                    with st.popover("📋 Como fazer esta revisão"):
                        for i, passo in enumerate(etapa["metodo"], start=1):
                            st.markdown(f"{i}. {passo}")
                    b1, b2, b3 = st.columns(3)
                    for col, chave in zip((b1, b2, b3), RESULTADOS_REVISAO):
                        if col.button(RESULTADOS_REVISAO[chave], key=f"revx_{chave}_{r['id']}"):
                            proxima = registrar_revisao(conn, r["id"], chave)
                            st.toast(f"Próxima revisão deste item: {proxima:%d/%m}")
                            st.rerun()
    st.markdown("---")

def blocos_para_repor(conn, meta_id):
    inicio = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id}", CRONO_INICIO.isoformat()))
    df = pd.read_sql_query("""SELECT t.id, t.nome, t.bloco, t.minutos_planejados, t.minutos_estudados, t.status,
                                     t.semana, t.dia, t.ordem, m.nome as materia
                              FROM topicos t JOIN materias m ON t.materia_id = m.id
                              WHERE m.meta_id = ? AND t.semana IS NOT NULL AND t.status != 'Concluído'""",
                           conn, params=(int(meta_id),))
    if df.empty:
        return df
    df['data'] = df.apply(lambda r: data_do_bloco(inicio, r['semana'], r['dia']), axis=1)
    df = df[(df['data'] < hoje()) | (df['status'] == 'Adiado')].copy()
    ordem_prio = {"Alta": 0, "Média": 1, "Baixa": 2}
    df['prio'] = df['materia'].apply(lambda n: ordem_prio.get(prioridade_da_materia(n), 1))
    df['falta'] = (df['minutos_planejados'].fillna(0) - df['minutos_estudados'].fillna(0)).clip(lower=0)
    return df.sort_values(['prio', 'data', 'ordem'])

def mostrar_rotina_cronograma(conn, meta_id, objetivo):
    """Tela do dia para objetivos com cronograma: revisões, blocos de hoje, escala e reposição."""
    semana_hoje, dia_hoje = semana_e_dia_de_hoje(meta_id)
    n_semanas = total_semanas(meta_id, conn)
    inicio_rot = datetime.date.fromisoformat(get_config(f"cronograma_inicio_{meta_id}", CRONO_INICIO.isoformat()))
    d_hoje = hoje()
    algum_rodando = False

    # NOVO: tempo líquido registrado pelo cronômetro
    min_hoje, min_semana = tempo_estudado(conn, objetivo)
    t1, t2 = st.columns(2)
    t1.metric("⏱️ Estudado hoje", fmt_horas(min_hoje))
    t2.metric("📅 Nesta semana", fmt_horas(min_semana))

    mostrar_revisoes_do_dia(conn, objetivo, fim_de_semana=dia_hoje > 4)

    escala_hoje = conn.execute("SELECT 1 FROM escalas WHERE data = ?", (d_hoje.isoformat(),)).fetchone() is not None
    if semana_hoje < 1:
        st.info(f"📆 O cronograma começa na segunda-feira, {inicio_rot:%d/%m/%Y}.")
    elif semana_hoje > n_semanas:
        st.success(f"🏁 O cronograma de {n_semanas} semanas terminou. Boa prova!")
    elif dia_hoje <= 4:
        if escala_hoje:
            st.warning("🚨 Hoje está registrado como dia de escala. Os blocos de hoje foram para a fila de reposição. Bom serviço!")
            if st.button("↩️ Desfazer: não estou mais escalado hoje"):
                conn.execute("DELETE FROM escalas WHERE data = ?", (d_hoje.isoformat(),))
                conn.execute("""UPDATE topicos SET status = 'Pendente' WHERE status = 'Adiado' AND semana = ? AND dia = ?
                                AND materia_id IN (SELECT id FROM materias WHERE meta_id = ?)""",
                             (int(semana_hoje), int(dia_hoje), int(meta_id)))
                conn.commit()
                st.rerun()
        else:
            with st.expander("🚨 Estou escalado hoje / plantão extra"):
                st.write("Os blocos de hoje que ainda não foram feitos vão para a **fila de reposição**. "
                         "Eles aparecem nos fins de semana e no fim desta tela, ordenados pela prioridade da matéria.")
                if st.button("Registrar escala de hoje", type="primary"):
                    conn.execute("INSERT OR REPLACE INTO escalas (data, obs) VALUES (?, ?)", (d_hoje.isoformat(), "escala/plantão"))
                    conn.execute("""UPDATE topicos SET status = 'Adiado' WHERE status IN ('Pendente', 'Parcial') AND semana = ? AND dia = ?
                                    AND materia_id IN (SELECT id FROM materias WHERE meta_id = ?)""",
                                 (int(semana_hoje), int(dia_hoje), int(meta_id)))
                    conn.commit()
                    st.rerun()
        if not escala_hoje:
            st.subheader(f"📆 Semana {semana_hoje} · {DIAS_SEMANA[dia_hoje]} – blocos de hoje")
            df_hoje = pd.read_sql_query("""
                SELECT t.id, t.nome, t.bloco, t.minutos_planejados, t.minutos_estudados, t.status, m.nome as materia
                FROM topicos t JOIN materias m ON t.materia_id = m.id
                WHERE m.meta_id = ? AND t.semana = ? AND t.dia = ?
                ORDER BY t.ordem
            """, conn, params=(int(meta_id), int(semana_hoje), int(dia_hoje)))
            if df_hoje.empty:
                st.info("Nenhum bloco previsto para hoje.")
            for _, row in df_hoje.iterrows():
                algum_rodando = mostrar_bloco(conn, row, objetivo, "hoje") or algum_rodando

    # Fila de reposição (blocos de dias anteriores que ficaram para trás)
    df_rep = blocos_para_repor(conn, meta_id)
    if not df_rep.empty:
        horas_rep = df_rep['falta'].sum() / 60
        st.markdown("---")
        fim_de_semana = dia_hoje > 4
        if fim_de_semana:
            horas_fds = float(get_config("horas_reposicao_fds", "3.0"))
            st.subheader(f"📌 Fim de semana: reposição ({len(df_rep)} blocos atrasados, {horas_rep:.1f} h)")
            st.caption(f"Sugestão para hoje: até {horas_fds:g} h, começando pelas matérias de maior prioridade. "
                       "Altere esse limite em '⚙️ Gerenciador' → '⚙️ Disp. de Tempo'.")
            acumulado, sugeridos = 0, []
            for _, r in df_rep.iterrows():
                if acumulado + r['falta'] > horas_fds * 60 and sugeridos:
                    break
                sugeridos.append(r)
                acumulado += r['falta']
            for r in sugeridos:
                algum_rodando = mostrar_bloco(conn, r, objetivo, "rep", r['data']) or algum_rodando
        else:
            st.subheader(f"📌 Reposição pendente: {len(df_rep)} blocos ({horas_rep:.1f} h)")
            if st.toggle("Mostrar os blocos para repor agora", key="mostrar_rep"):
                for _, r in df_rep.head(6).iterrows():
                    algum_rodando = mostrar_bloco(conn, r, objetivo, "rep", r['data']) or algum_rodando
                if len(df_rep) > 6:
                    st.caption(f"E mais {len(df_rep) - 6} blocos. Eles aparecem aqui conforme você conclui os primeiros.")
    elif dia_hoje > 4 and 1 <= semana_hoje <= n_semanas:
        st.success("🎉 Nada atrasado. Aproveite o fim de semana para descansar ou para fazer questões.")


# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🛡️ Sistema Unificado de Gestão de Estudos")

menu = st.sidebar.radio("Navegação", [
    "📅 Meta & Rotina do Dia",
    "🧭 Planejar Estudos",
    "🗓️ Cronograma Semanal",
    "📋 Checklist & Acompanhamento",
    "📝 Registrar Questões",
    "📈 Desempenho em Questões",
    "📊 Dashboard de Evolução",
    "⚙️ Gerenciador"
])

# NOVO: situação da cópia na nuvem, sempre visível na barra lateral
_est_nuvem = estado_nuvem()
if _est_nuvem["estado"] == "ligada":
    if _est_nuvem["erro"]:
        st.sidebar.warning("☁️ " + _est_nuvem["erro"])
    elif _est_nuvem["ultimo_envio"]:
        st.sidebar.success(f"☁️ Cópia na nuvem salva às {_est_nuvem['ultimo_envio']:%H:%M}")
    else:
        st.sidebar.info("☁️ Cópia na nuvem ligada")
    if _est_nuvem["restaurado"]:
        st.sidebar.info("☁️ O servidor reiniciou e seus dados foram trazidos da nuvem.")
elif _est_nuvem["estado"] == "erro":
    st.sidebar.error("☁️ " + _est_nuvem["erro"])
else:
    st.sidebar.warning("☁️ Cópia na nuvem desligada. Veja '⚙️ Gerenciador' → '☁️ Nuvem'.")

conn = get_db()
preparar_edital_cfo_uma_vez()

# =============================================================================
# MENU 1: META & ROTINA DO DIA
# =============================================================================
if menu == "📅 Meta & Rotina do Dia":
    st.header("🎯 Sugestão Diária de Estudo e Rotina Policial")
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    if df_metas.empty:
        st.warning("Nenhum objetivo cadastrado. Cadastre um em '⚙️ Gerenciador'.")
    else:
        meta_sel_rotina = st.selectbox("Selecione o Objetivo do Dia:", df_metas['nome'].tolist())
        meta_id_rotina = df_metas[df_metas['nome'] == meta_sel_rotina]['id'].values[0]

        # Objetivo com cronograma: revisões, blocos de hoje, escala e reposição
        if meta_tem_cronograma(meta_id_rotina, conn):
            mostrar_rotina_cronograma(conn, meta_id_rotina, meta_sel_rotina)
            conn.close()
            st.stop()

        escalado = st.checkbox("🚨 Estarei Escalado Hoje / Plantão Extra (Suspender estudos hoje)", value=False)
        if escalado:
            st.warning("⚠️ **Modo Plantão/Escala Ativado:** O ciclo de estudos foi pausado para hoje. Bons serviços no plantão!")
            conn.close()
            st.stop()
        horas_disp = float(get_config("horas_estudo_dia", "3.0"))
        turno_pref = get_config("turno_estudo", "Noite")
        st.info(f"💡 **Disponibilidade Hoje:** {horas_disp} horas no turno da **{turno_pref}**.")

        query_proximos = """
            SELECT t.id as topico_id, t.nome as topico_nome, m.id as materia_id, m.nome as materia_nome, t.status, t.teoria
            FROM topicos t
            JOIN materias m ON t.materia_id = m.id
            WHERE m.meta_id = ? AND t.status != 'Concluído' AND t.teoria = 0
            ORDER BY m.id, t.id
        """
        df_proximos = pd.read_sql_query(query_proximos, conn, params=(int(meta_id_rotina),))
        
        if df_proximos.empty:
            st.balloons()
            st.success("🎉 Parabéns! Todos os tópicos deste objetivo foram concluídos!")
        else:
            topicos_sugeridos = df_proximos.groupby('materia_nome').first().reset_index().head(2)
            
            niveis = []
            pesos = []
            for idx, row in topicos_sugeridos.iterrows():
                nv = calcular_nivel_materia(row['materia_id'], conn)
                niveis.append(nv)
                pesos.append(max(1.0, 11.0 - nv))
            
            soma_pesos = sum(pesos)
            
            st.subheader("📌 Recomendações e Cronômetro de Estudo:")
            
            for i, (_, row) in enumerate(topicos_sugeridos.iterrows()):
                prop_tempo = pesos[i] / soma_pesos
                tempo_horas = horas_disp * prop_tempo
                total_segundos = int(tempo_horas * 3600)
                
                horas_f = int(tempo_horas)
                minutos_f = int(round((tempo_horas - horas_f) * 60))
                tempo_str = f"{horas_f}h{minutos_f:02d}m" if horas_f > 0 else f"{minutos_f} min"
                
                topico_id = row['topico_id']
                
                timer_data = get_timer_state(topico_id, total_segundos)
                status_timer = timer_data['status']
                seg_restantes = timer_data['restante']

                with st.expander(f"📖 **{row['materia_nome']}** | Tempo Adaptativo: **{tempo_str}** | Domínio: `{niveis[i]}/10`", expanded=True):
                    st.markdown(f"**Conteúdo Específico:** {row['topico_nome']}")
                    st.write(f"**Status Atual:** `{row['status']}`")
                    
                    st.markdown("---")
                    st.markdown("#### ⏱️ Cronômetro Imunizado contra Quedas")
                    
                    if status_timer == 'FINISHED':
                        st.success("🔔 **Tempo de estudo concluído para esta matéria!**")
                    
                    hrs_c = seg_restantes // 3600
                    mins_c = (seg_restantes % 3600) // 60
                    secs_c = seg_restantes % 60
                    
                    st.markdown(f"### ⏳ `{hrs_c:02d}:{mins_c:02d}:{secs_c:02d}`")
                    
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("▶️ Iniciar / Continuar", key=f"start_{topico_id}"):
                            set_timer_start(topico_id, seg_restantes)
                            st.rerun()
                    with c2:
                        if st.button("⏸️ Pausar", key=f"pause_{topico_id}"):
                            set_timer_pause(topico_id, seg_restantes)
                            st.rerun()
                    with c3:
                        if st.button("🔄 Reiniciar / Zerar", key=f"reset_{topico_id}"):
                            set_timer_stop(topico_id)
                            st.rerun()

                    if status_timer == 'RODANDO':
                        time.sleep(1)
                        st.rerun()

                    st.markdown("---")
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button(f"✅ Concluído Totalmente", key=f"conc_{topico_id}"):
                            c = conn.cursor()
                            c.execute("UPDATE topicos SET status = 'Concluído', teoria = 1, resumo = 1 WHERE id = ?", (int(topico_id),))
                            conn.commit()
                            set_timer_stop(topico_id)
                            st.success("Tópico Concluído!")
                            st.rerun()
                    with col_b:
                        if st.button(f"⏳ Parcialmente Estudado", key=f"parc_{topico_id}"):
                            c = conn.cursor()
                            c.execute("UPDATE topicos SET status = 'Parcial', teoria = 1 WHERE id = ?", (int(topico_id),))
                            conn.commit()
                            set_timer_stop(topico_id)
                            st.info("Marcado como Parcial.")
                            st.rerun()

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
        d_hoje_pl = hoje()
        proxima_segunda = d_hoje_pl + datetime.timedelta(days=(7 - d_hoje_pl.weekday()) % 7)
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
                }, width="stretch", hide_index=True)
                with st.expander("Ver a semana 1"):
                    df_v = df_pl[df_pl["Semana"] == 1].copy()
                    df_v["Dia"] = df_v["Dia"].apply(lambda d: DIAS_SEMANA[int(d)])
                    st.dataframe(df_v[["Dia", "Bloco", "Minutos", "Matéria", "Tópico"]], width="stretch", hide_index=True)
                
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
                    "Status": st.column_config.SelectboxColumn("Status", options=STATUS_BLOCO, required=True)
                },
                disabled=["Dia", "Bloco", "Matéria", "Tópico", "Previsto_min"],
                hide_index=True,
                width="stretch",
                key=f"editor_semana_{meta_id_cr}_{semana_sel}"
            )

            if st.button("💾 Salvar a semana"):
                for _, row in editado.iterrows():
                    salvar_status_topico(conn, row['id'], row['Status'], int(row['Estudado_min'] or 0))
                st.success("Semana salva! O Dashboard e o Checklist já foram atualizados.")
                st.rerun()

elif menu == "📋 Checklist & Acompanhamento":
    st.header("📋 Checklist & Acompanhamento")
    aba_edital, aba_blocos = st.tabs(["📚 Itens do edital", "🗓️ Blocos do cronograma"])

    # ------------------------------------------------------------------ itens do edital
    with aba_edital:
        objetivos = objetivos_com_edital(conn)
        if not objetivos:
            st.info("Nenhum edital com itens cadastrado. Importe um edital em '⚙️ Gerenciador' → '📅 Cronogramas'.")
        else:
            col_o, col_i = st.columns([2, 1])
            with col_o:
                obj_ck = st.selectbox("Objetivo:", objetivos,
                                      index=objetivos.index(CRONO_META_NOME) if CRONO_META_NOME in objetivos else 0, key="ck_obj")
            with col_i:
                idiomas = ["Inglês", "Espanhol"]
                novo_idioma = st.radio("Língua estrangeira da prova:", idiomas, horizontal=True,
                                       index=idiomas.index(idioma_escolhido()), key="ck_idioma")
                if novo_idioma != idioma_escolhido():
                    set_config("idioma_prova", novo_idioma)
                    st.rerun()

            df_it = pd.read_sql_query("""SELECT id, materia, ordem, item, prioridade, teoria, resumo, material,
                                                data_teoria, n_revisoes, proxima_revisao
                                         FROM edital_itens WHERE objetivo = ? ORDER BY materia, ordem""", conn, params=(obj_ck,))
            df_it = filtrar_idioma(df_it)
            df_q = carregar_questoes(conn, obj_ck)
            if not df_q.empty:
                por_item = df_q.groupby("item_id")[["total", "acertos"]].sum()
                por_mat_q = df_q.groupby("materia")[["total", "acertos"]].sum()
            else:
                por_item = pd.DataFrame(columns=["total", "acertos"])
                por_mat_q = pd.DataFrame(columns=["total", "acertos"])

            # Visão geral por matéria
            d_iso = hoje().isoformat()
            linhas = []
            for mat, g in df_it.groupby("materia", sort=False):
                q = por_mat_q.loc[mat] if mat in por_mat_q.index else None
                tot_q = int(q["total"]) if q is not None else 0
                linhas.append({"Matéria": mat, "Itens": len(g),
                               "Teoria feita": g["teoria"].sum() / len(g) if len(g) else 0.0,
                               "Revisões atrasadas": int(((g["teoria"] == 1) & (g["proxima_revisao"].fillna("9999") < d_iso)).sum()),
                               "Questões": tot_q,
                               "Acerto (%)": pct(int(q["acertos"]), tot_q) if tot_q else None})
            if linhas:
                total_itens = len(df_it)
                feitos = int(df_it["teoria"].sum())
                k1, k2, k3 = st.columns(3)
                k1.metric("Itens do edital com teoria", f"{feitos}/{total_itens}")
                k2.metric("Avanço do edital", f"{100 * feitos / total_itens:.0f}%" if total_itens else "0%")
                k3.progress(feitos / total_itens if total_itens else 0.0)
                df_linhas = pd.DataFrame(linhas)
                df_linhas["Acerto (%)"] = pd.to_numeric(df_linhas["Acerto (%)"], errors="coerce")
                st.dataframe(df_linhas, column_config={
                    "Teoria feita": st.column_config.ProgressColumn("Teoria feita", min_value=0.0, max_value=1.0, format="percent"),
                    "Acerto (%)": st.column_config.NumberColumn("Acerto (%)", format="%.1f")
                }, width="stretch", hide_index=True)

            st.markdown("---")
            materias_ck = list(dict.fromkeys(df_it["materia"].tolist()))
            if materias_ck:
                mat_ck = st.selectbox("Matéria para marcar:", materias_ck, key="ck_mat")
                g = df_it[df_it["materia"] == mat_ck].copy()
                g["Questões"] = g["id"].apply(lambda i: int(por_item.loc[i, "total"]) if i in por_item.index else 0)
                g["Acerto (%)"] = pd.to_numeric(g["id"].apply(lambda i: pct(int(por_item.loc[i, "acertos"]), int(por_item.loc[i, "total"]))
                                                              if i in por_item.index else None), errors="coerce")
                g["Teoria"] = g["teoria"].astype(bool)
                g["Resumo"] = g["resumo"].astype(bool)
                g["Próx. revisão"] = g["proxima_revisao"].apply(
                    lambda v: datetime.date.fromisoformat(v).strftime("%d/%m") if isinstance(v, str) and v else "")
                st.caption("Marque **Teoria** quando estudar o item. As revisões são agendadas sozinhas: 1 dia, 7 dias, 30 dias e "
                           "depois a cada 60 dias, ajustadas pelo quanto você lembrou em cada uma. "
                           "Em **Material**, anote a aula do PDF (ex.: \"Estratégia, Aula 03\"). Depois toque em Salvar.")
                editado_ck = st.data_editor(
                    g[["id", "item", "prioridade", "Teoria", "Resumo", "material", "n_revisoes", "Próx. revisão", "Questões", "Acerto (%)"]],
                    column_config={
                        "id": None,
                        "item": st.column_config.TextColumn("Item do edital", width="large"),
                        "prioridade": st.column_config.SelectboxColumn("Prioridade", options=["Alta", "Média", "Baixa"], required=True),
                        "material": st.column_config.TextColumn("Material (aula)"),
                        "n_revisoes": st.column_config.NumberColumn("Revisões feitas"),
                        "Acerto (%)": st.column_config.NumberColumn("Acerto (%)", format="%.1f"),
                    },
                    disabled=["item", "n_revisoes", "Próx. revisão", "Questões", "Acerto (%)"],
                    hide_index=True, width="stretch", key=f"ed_itens_{obj_ck}_{mat_ck}")
                if st.button("💾 Salvar esta matéria", type="primary"):
                    antes = g.set_index("id")["teoria"].to_dict()
                    for _, r in editado_ck.iterrows():
                        iid = int(r["id"])
                        if r["Teoria"] and not antes.get(iid):
                            marcar_teoria_itens(conn, [iid])
                        elif not r["Teoria"] and antes.get(iid):
                            desmarcar_teoria_item(conn, iid)
                        conn.execute("UPDATE edital_itens SET resumo = ?, material = ?, prioridade = ? WHERE id = ?",
                                     (1 if r["Resumo"] else 0, str(r["material"] or ""), r["prioridade"], iid))
                    conn.commit()
                    st.success("Checklist salvo!")
                    st.rerun()

    # ------------------------------------------------------------------ blocos do cronograma (como antes)
    with aba_blocos:
        df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
        if df_metas.empty:
            st.info("Nenhum objetivo cadastrado.")
        else:
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                meta_sel = st.selectbox("1. Selecione o Objetivo", df_metas['nome'].tolist(), key="bl_meta")
                meta_id = df_metas[df_metas['nome'] == meta_sel]['id'].values[0]
            df_mat = pd.read_sql_query("SELECT id, nome FROM materias WHERE meta_id = ?", conn, params=(int(meta_id),))
            if df_mat.empty:
                st.warning("Nenhuma matéria cadastrada para este objetivo.")
            else:
                with col_m2:
                    mat_sel = st.selectbox("2. Filtrar por Matéria", df_mat['nome'].tolist(), key="bl_mat")
                    mat_id = df_mat[df_mat['nome'] == mat_sel]['id'].values[0]
                nivel_atual = calcular_nivel_materia(mat_id, conn)
                st.info(f"📊 **Nível de Domínio Calculado em {mat_sel}:** `{nivel_atual} / 10.0`")
                df_topicos = pd.read_sql_query("""SELECT id, nome as Topico, teoria as Videoaula_PDF, resumo as Resumo_Mapa, status as Status
                                                  FROM topicos WHERE materia_id = ?""", conn, params=(int(mat_id),))
                if df_topicos.empty:
                    st.info("Nenhum tópico cadastrado nesta matéria.")
                else:
                    df_topicos['Videoaula_PDF'] = df_topicos['Videoaula_PDF'].astype(bool)
                    df_topicos['Resumo_Mapa'] = df_topicos['Resumo_Mapa'].astype(bool)
                    edited_df = st.data_editor(
                        df_topicos[['id', 'Topico', 'Videoaula_PDF', 'Resumo_Mapa', 'Status']],
                        column_config={
                            "Videoaula_PDF": st.column_config.CheckboxColumn("Teoria"),
                            "Resumo_Mapa": st.column_config.CheckboxColumn("Resumo/Mapa"),
                            "Status": st.column_config.SelectboxColumn("Status de Conclusão", options=STATUS_BLOCO, required=True)
                        },
                        disabled=["id", "Topico"], hide_index=True, width="stretch")
                    if st.button("💾 Salvar Alterações na Matéria"):
                        c = conn.cursor()
                        for idx, row in edited_df.iterrows():
                            is_teoria = 1 if row['Videoaula_PDF'] else 0
                            is_resumo = 1 if row['Resumo_Mapa'] else 0
                            status_str = row['Status']
                            if is_teoria == 1 and status_str == 'Pendente':
                                status_str = 'Concluído'
                            elif status_str == 'Concluído':
                                is_teoria = 1
                                if is_resumo == 0:
                                    is_resumo = 1
                            elif status_str == 'Parcial':
                                is_teoria = 1
                            c.execute("UPDATE topicos SET teoria = ?, resumo = ?, status = ? WHERE id = ?",
                                      (is_teoria, is_resumo, status_str, int(row['id'])))
                        conn.commit()
                        st.success("Progresso salvo e sincronizado com o Dashboard de Evolução!")
                        st.rerun()

# =============================================================================
# MENU 3: REGISTRAR QUESTÕES (NOVO: por item do edital, com fonte e motivo do erro)
# =============================================================================
elif menu == "📝 Registrar Questões":
    st.header("📝 Registrar Questões")
    objetivos = objetivos_com_edital(conn)
    if not objetivos:
        st.warning("Nenhum edital com itens cadastrado. Importe um edital em '⚙️ Gerenciador' → '📅 Cronogramas'.")
    else:
        obj_q = st.selectbox("Objetivo:", objetivos,
                             index=objetivos.index(CRONO_META_NOME) if CRONO_META_NOME in objetivos else 0, key="q_obj")
        df_itq = filtrar_idioma(pd.read_sql_query("SELECT id, materia, item FROM edital_itens WHERE objetivo = ? ORDER BY materia, ordem",
                                                  conn, params=(obj_q,)))
        materias_q = list(dict.fromkeys(df_itq["materia"].tolist()))
        aba_um, aba_sim, aba_hist = st.tabs(["➕ Um lote de questões", "🧪 Simulado completo", "🗂️ Histórico e correções"])

        with aba_um:
            mat_q = st.selectbox("Matéria:", materias_q, key="q_mat")
            itens_mat = df_itq[df_itq["materia"] == mat_q]
            opcoes_item = [0] + itens_mat["id"].astype(int).tolist()
            rot_item = {0: "(sem item específico)"}
            rot_item.update({int(r["id"]): r["item"] for _, r in itens_mat.iterrows()})
            with st.form("form_questoes", clear_on_submit=True):
                item_q = st.selectbox("Item do edital:", opcoes_item, format_func=lambda i: rot_item[i])
                c1, c2, c3 = st.columns(3)
                with c1:
                    data_q = st.date_input("Data:", value=hoje(), format="DD/MM/YYYY")
                with c2:
                    total_q = st.number_input("Questões resolvidas:", min_value=1, value=10, step=1)
                with c3:
                    acertos_q = st.number_input("Acertos:", min_value=0, value=7, step=1)
                fonte_q = st.selectbox("De onde vieram as questões:", FONTES_QUESTOES)
                st.markdown("**Por que você errou?** (distribua os erros; é isso que gera as recomendações)")
                m1, m2, m3, m4 = st.columns(4)
                valores_motivo = {}
                for col, (chave, (rotulo, _)) in zip((m1, m2, m3, m4), MOTIVOS_ERRO.items()):
                    with col:
                        valores_motivo[chave] = st.number_input(rotulo, min_value=0, value=0, step=1, key=f"mot_{chave}")
                obs_q = st.text_input("Observação (opcional): o que você aprendeu com os erros")
                enviar_q = st.form_submit_button("💾 Salvar questões", type="primary")
            if enviar_q:
                erros_q = int(total_q) - int(acertos_q)
                soma_mot = sum(valores_motivo.values())
                if acertos_q > total_q:
                    st.error("Os acertos não podem ser maiores que o total de questões.")
                elif soma_mot > erros_q:
                    st.error(f"Você distribuiu {soma_mot} erros, mas errou só {erros_q}. Corrija os motivos.")
                else:
                    conn.execute("""INSERT INTO questoes (data, objetivo, materia, item_id, total, acertos, fonte,
                                    erro_conteudo, erro_interpretacao, erro_atencao, erro_tempo, obs)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                 (data_q.isoformat(), obj_q, mat_q, int(item_q) or None, int(total_q), int(acertos_q), fonte_q,
                                  valores_motivo["erro_conteudo"], valores_motivo["erro_interpretacao"],
                                  valores_motivo["erro_atencao"], valores_motivo["erro_tempo"], obs_q))
                    conn.commit()
                    taxa = 100 * acertos_q / total_q
                    msg = f"Salvo: {acertos_q}/{total_q} ({taxa:.0f}% de acerto)."
                    if erros_q and soma_mot < erros_q:
                        msg += f" Dica: {erros_q - soma_mot} erro(s) ficaram sem motivo; classificar todos melhora as recomendações."
                    (st.success if taxa >= 70 else st.warning)(msg)

        with aba_sim:
            st.write("Lance o resultado de um simulado inteiro de uma vez, matéria por matéria.")
            base_sim = []
            for mat in materias_q:
                qtd = EDITAL_CFO[mat][1] if (obj_q == CRONO_META_NOME and mat in EDITAL_CFO) else 0
                if mat == "Redação":
                    continue
                base_sim.append({"Matéria": mat, "Questões": qtd, "Acertos": 0})
            with st.form("form_simulado"):
                data_sim = st.date_input("Data do simulado:", value=hoje(), format="DD/MM/YYYY")
                nome_sim = st.text_input("Nome do simulado (ex.: Simulado 1 Estratégia):")
                tabela_sim = st.data_editor(pd.DataFrame(base_sim), disabled=["Matéria"], hide_index=True,
                                            width="stretch", key="ed_sim")
                conferi_sim = st.checkbox("Conferi os números de acertos de cada matéria")
                salvar_sim = st.form_submit_button("💾 Salvar simulado", type="primary")
            if salvar_sim and not conferi_sim:
                st.warning("Preencha os acertos e marque \"Conferi os números\" antes de salvar.")
            elif salvar_sim:
                invalidas = tabela_sim[tabela_sim["Acertos"] > tabela_sim["Questões"]]
                if not invalidas.empty:
                    st.error("Há matérias com mais acertos do que questões: " + ", ".join(invalidas["Matéria"]))
                else:
                    n = 0
                    for _, r in tabela_sim.iterrows():
                        if int(r["Questões"]) > 0:
                            conn.execute("""INSERT INTO questoes (data, objetivo, materia, item_id, total, acertos, fonte, obs)
                                            VALUES (?, ?, ?, NULL, ?, ?, 'Simulado', ?)""",
                                         (data_sim.isoformat(), obj_q, r["Matéria"], int(r["Questões"]), int(r["Acertos"]), nome_sim))
                            n += 1
                    conn.commit()
                    tq, ta = int(tabela_sim["Questões"].sum()), int(tabela_sim["Acertos"].sum())
                    st.success(f"Simulado salvo ({n} matérias): {ta}/{tq} acertos ({pct(ta, tq) or 0:.0f}%).")

        with aba_hist:
            df_h = carregar_questoes(conn, obj_q)
            if df_h.empty:
                st.info("Nenhuma questão registrada ainda.")
            else:
                df_h = df_h.sort_values(["data", "id"], ascending=False).head(60)
                df_h["Data"] = df_h["data"].apply(lambda v: datetime.date.fromisoformat(v).strftime("%d/%m/%Y"))
                df_h["Acerto (%)"] = (100 * df_h["acertos"] / df_h["total"]).round(0)
                st.dataframe(df_h[["id", "Data", "materia", "item", "total", "acertos", "Acerto (%)", "fonte"]].rename(
                    columns={"id": "Nº", "materia": "Matéria", "item": "Item", "total": "Questões", "acertos": "Acertos", "fonte": "Fonte"}),
                    width="stretch", hide_index=True)
                apagar = st.multiselect("Lançou algo errado? Escolha o Nº para apagar:", df_h["id"].astype(int).tolist(),
                                        placeholder="Escolha o número do registro")
                if apagar and st.button("🗑️ Apagar os registros escolhidos"):
                    for i in apagar:
                        conn.execute("DELETE FROM questoes WHERE id = ?", (int(i),))
                    conn.commit()
                    st.success("Registros apagados.")
                    st.rerun()

# =============================================================================
# NOVO: DESEMPENHO EM QUESTÕES (estatísticas e recomendações)
# =============================================================================
elif menu == "📈 Desempenho em Questões":
    st.header("📈 Desempenho em Questões")
    objetivos = objetivos_com_edital(conn)
    if not objetivos:
        st.info("Nenhum edital com itens cadastrado.")
    else:
        c_o, c_p = st.columns([2, 2])
        with c_o:
            obj_d = st.selectbox("Objetivo:", objetivos,
                                 index=objetivos.index(CRONO_META_NOME) if CRONO_META_NOME in objetivos else 0, key="d_obj")
        with c_p:
            periodo = st.radio("Período:", ["Tudo", "Últimos 30 dias", "Últimos 7 dias"], horizontal=True)
        desde = None if periodo == "Tudo" else hoje() - datetime.timedelta(days=30 if "30" in periodo else 7)
        df_d = carregar_questoes(conn, obj_d, desde)
        df_itens_d = filtrar_idioma(pd.read_sql_query("""SELECT id, materia, item, prioridade, teoria, proxima_revisao
                                                         FROM edital_itens WHERE objetivo = ?""", conn, params=(obj_d,)))
        meta_semana = int(get_config("meta_questoes_semana", "100"))
        inicio_semana = hoje() - datetime.timedelta(days=hoje().weekday())
        df_semana = carregar_questoes(conn, obj_d, inicio_semana)
        feitas_semana = int(df_semana["total"].sum()) if not df_semana.empty else 0

        if df_d.empty:
            st.info("Ainda não há questões neste período. Registre em '📝 Registrar Questões' e os gráficos aparecem aqui.")
        else:
            tot, ace = int(df_d["total"].sum()), int(df_d["acertos"].sum())
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Questões resolvidas", f"{tot}")
            k2.metric("Acerto geral", f"{pct(ace, tot):.1f}%")
            k3.metric("Questões nesta semana", f"{feitas_semana}", f"meta: {meta_semana}", delta_color="off")
            k4.metric("Itens do edital com teoria", f"{int(df_itens_d['teoria'].sum())}/{len(df_itens_d)}")
            st.progress(min(1.0, feitas_semana / meta_semana) if meta_semana else 0.0)

            # Alerta de eliminação: mínimo de 30% em cada bloco e nenhuma disciplina zerada (item 10.1.4 do edital)
            if obj_d == CRONO_META_NOME:
                st.subheader("🚦 Mínimos do edital (30% por bloco, nenhuma matéria zerada)")
                cols_b = st.columns(3)
                for col, bloco in zip(cols_b, ["Bloco I", "Bloco II", "Bloco III"]):
                    mats_b = [m for m, v in EDITAL_CFO.items() if v[0] == bloco]
                    sub = df_d[df_d["materia"].isin(mats_b)]
                    t_b, a_b = int(sub["total"].sum()), int(sub["acertos"].sum())
                    with col:
                        if t_b == 0:
                            st.info(f"**{bloco}**: sem questões registradas")
                        else:
                            p_b = pct(a_b, t_b)
                            (st.error if p_b < 30 else st.warning if p_b < 50 else st.success)(
                                f"**{bloco}**: {p_b:.0f}% de acerto ({t_b} questões)")
                        sem_dados = [m for m in mats_b if m not in set(sub["materia"])]
                        if sem_dados:
                            st.caption("Sem questões: " + ", ".join(sem_dados))

            # Por matéria
            st.subheader("📚 Acerto por matéria")
            pm = df_d.groupby("materia")[["total", "acertos"]].sum()
            pm["Acerto (%)"] = (100 * pm["acertos"] / pm["total"]).round(1)
            pm = pm.sort_values("Acerto (%)")
            st.bar_chart(pm["Acerto (%)"], horizontal=True)
            tabela_pm = pm.reset_index().rename(columns={"materia": "Matéria", "total": "Questões", "acertos": "Acertos"})
            st.dataframe(tabela_pm, width="stretch", hide_index=True)

            # Evolução semanal
            st.subheader("📆 Evolução semana a semana")
            df_ev = df_d.copy()
            df_ev["Semana"] = df_ev["data"].apply(lambda v: (datetime.date.fromisoformat(v) -
                                                             datetime.timedelta(days=datetime.date.fromisoformat(v).weekday())).strftime("%d/%m"))
            df_ev["ord"] = df_ev["data"].apply(lambda v: datetime.date.fromisoformat(v) -
                                               datetime.timedelta(days=datetime.date.fromisoformat(v).weekday()))
            ev = df_ev.groupby(["ord", "Semana"])[["total", "acertos"]].sum().reset_index().sort_values("ord")
            ev["Acerto (%)"] = (100 * ev["acertos"] / ev["total"]).round(1)
            ev["Semana"] = [f"{n:02d} · {d:%d/%m}" for n, d in enumerate(ev["ord"], start=1)]  # numerado para ficar em ordem
            ce1, ce2 = st.columns(2)
            with ce1:
                st.caption("Acerto (%) por semana (início da semana)")
                st.line_chart(ev.set_index("Semana")["Acerto (%)"])
            with ce2:
                st.caption("Questões resolvidas por semana")
                st.bar_chart(ev.set_index("Semana")["total"].rename("Questões"))

            # Ranking dos piores itens
            st.subheader("🔻 Itens com pior desempenho")
            minimo = st.slider("Considerar só itens com pelo menos N questões:", 3, 30, 5)
            pi = df_d[df_d["item_id"].notna()].groupby(["materia", "item", "prioridade"])[["total", "acertos"]].sum().reset_index()
            pi = pi[pi["total"] >= minimo].copy()
            if pi.empty:
                st.caption("Ainda não há itens com questões suficientes. Registre as questões escolhendo o item do edital.")
            else:
                pi["Acerto (%)"] = (100 * pi["acertos"] / pi["total"]).round(1)
                st.dataframe(pi.sort_values("Acerto (%)").head(10).rename(
                    columns={"materia": "Matéria", "item": "Item", "prioridade": "Prioridade", "total": "Questões", "acertos": "Acertos"}),
                    width="stretch", hide_index=True)

            # Motivos dos erros
            st.subheader("🧠 Por que você está errando")
            cols_mot = list(MOTIVOS_ERRO.keys())
            soma_mot = df_d[cols_mot].sum()
            erros_tot = int(df_d["erros"].sum())
            classificados = int(soma_mot.sum())
            if classificados == 0:
                st.caption("Nenhum erro classificado ainda. Ao registrar questões, diga o motivo dos erros para receber orientações.")
            else:
                df_mot = pd.DataFrame({"Motivo": [MOTIVOS_ERRO[k][0] for k in cols_mot], "Erros": [int(soma_mot[k]) for k in cols_mot]})
                st.bar_chart(df_mot.set_index("Motivo"), horizontal=True)
                st.caption(f"{classificados} de {erros_tot} erros classificados.")
                principal = soma_mot.idxmax()
                st.info(f"**Seu erro mais comum: {MOTIVOS_ERRO[principal][0]}.** {MOTIVOS_ERRO[principal][1]}")
                por_mat_mot = df_d.groupby("materia")[cols_mot].sum()
                por_mat_mot = por_mat_mot[por_mat_mot.sum(axis=1) > 0]
                if not por_mat_mot.empty:
                    dicas = []
                    for mat, r in por_mat_mot.iterrows():
                        k = r.idxmax()
                        dicas.append({"Matéria": mat, "Erro mais comum": MOTIVOS_ERRO[k][0], "O que fazer": MOTIVOS_ERRO[k][1]})
                    st.dataframe(pd.DataFrame(dicas), width="stretch", hide_index=True)

        # Reforço da semana (aparece mesmo com poucas questões)
        st.subheader("🎯 O que reforçar nesta semana")
        sugestoes = []
        if not df_d.empty:
            pi_all = df_d[df_d["item_id"].notna()].groupby(["materia", "item", "prioridade"])[["total", "acertos"]].sum().reset_index()
            pi_all = pi_all[pi_all["total"] >= 3].copy()
            if not pi_all.empty:
                pontos = {m: v[2] for m, v in EDITAL_CFO.items()} if obj_d == CRONO_META_NOME else {}
                pi_all["taxa"] = pi_all["acertos"] / pi_all["total"]
                pi_all["nota"] = (1 - pi_all["taxa"]) * pi_all["materia"].map(lambda m: pontos.get(m, 5)) * \
                                 pi_all["prioridade"].map(lambda p: FATOR_PRIO_ITEM.get(p, 1.0))
                for _, r in pi_all[pi_all["taxa"] < 0.7].sort_values("nota", ascending=False).head(5).iterrows():
                    sugestoes.append(f"**{r['materia']} · {r['item']}**: {100 * r['taxa']:.0f}% de acerto em {int(r['total'])} questões. "
                                     "Revise a teoria e faça mais 10 questões do item.")
        treinados = set(df_d["item_id"].dropna().astype(int)) if not df_d.empty else set()
        sem_treino = df_itens_d[(df_itens_d["teoria"] == 1) & (~df_itens_d["id"].isin(treinados))]
        sem_treino = sem_treino.assign(p=sem_treino["prioridade"].map({"Alta": 0, "Média": 1, "Baixa": 2})).sort_values("p")
        for _, r in sem_treino.head(5).iterrows():
            sugestoes.append(f"**{r['materia']} · {r['item']}**: você estudou a teoria mas ainda não registrou questões. "
                             "Faça pelo menos 10.")
        atrasadas = df_itens_d[(df_itens_d["teoria"] == 1) & (df_itens_d["proxima_revisao"].fillna("9999") < hoje().isoformat())]
        if len(atrasadas):
            sugestoes.append(f"Você tem **{len(atrasadas)} revisões atrasadas**. Elas aparecem em '📅 Meta & Rotina do Dia'.")
        if obj_d == CRONO_META_NOME:
            ultimos14 = carregar_questoes(conn, obj_d, hoje() - datetime.timedelta(days=14))
            estudadas = set(df_itens_d[df_itens_d["teoria"] == 1]["materia"])
            paradas = [m for m in estudadas if ultimos14.empty or m not in set(ultimos14["materia"])]
            if paradas:
                sugestoes.append("Matérias já estudadas e **sem questões há 14 dias**: " + ", ".join(sorted(paradas)) +
                                 ". Faça uma rodada curta para não esquecer.")
        if sugestoes:
            for s_ in sugestoes:
                st.markdown("- " + s_)
        else:
            st.caption("Sem pendências por enquanto. Continue registrando questões e marcando a teoria no checklist.")

        # NOVO: como estão as revisões
        st.subheader("🔁 Revisões")
        df_rl = pd.read_sql_query("""SELECT r.data, r.resultado, i.materia, i.item FROM revisoes_log r
                                     JOIN edital_itens i ON r.item_id = i.id WHERE i.objetivo = ?""", conn, params=(obj_d,))
        if desde is not None and not df_rl.empty:
            df_rl = df_rl[df_rl["data"] >= desde.isoformat()]
        if df_rl.empty:
            st.caption("Nenhuma revisão registrada neste período.")
        else:
            r1, r2, r3 = st.columns(3)
            r1.metric("Revisões feitas", len(df_rl))
            r2.metric("Lembrei bem", f"{100 * (df_rl['resultado'] == 'bem').mean():.0f}%")
            r3.metric("Esqueci", f"{100 * (df_rl['resultado'] == 'esqueci').mean():.0f}%")
            esquecidos = df_rl[df_rl["resultado"] == "esqueci"].groupby(["materia", "item"]).size().sort_values(ascending=False)
            if not esquecidos.empty:
                st.caption("Itens que você mais esquece (merecem um resumo novo ou mais flashcards):")
                st.dataframe(esquecidos.head(8).rename("Vezes que esqueceu").reset_index().rename(
                    columns={"materia": "Matéria", "item": "Item"}), width="stretch", hide_index=True)
            if (df_rl["resultado"] == "esqueci").mean() > 0.3:
                st.warning("Você está esquecendo mais de 30% dos itens nas revisões. Na primeira revisão, capriche nos "
                           "flashcards e escreva de memória antes de reler: esse esforço de lembrar é o que mais fixa.")

        with st.expander("⚙️ Meta semanal de questões"):
            nova_meta = st.number_input("Quantas questões você quer resolver por semana?", min_value=10, max_value=2000,
                                        value=meta_semana, step=10)
            if st.button("Salvar meta"):
                set_config("meta_questoes_semana", int(nova_meta))
                st.rerun()

# =============================================================================
# MENU 4: DASHBOARD DE EVOLUÇÃO
# =============================================================================
elif menu == "📊 Dashboard de Evolução":
    st.header("📊 Dashboard Geral de Desempenho")
    
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.warning("Nenhum objetivo ativo para gerar relatórios.")
    else:
        tabs = st.tabs(df_metas['nome'].tolist())
        
        for idx, row_meta in df_metas.iterrows():
            with tabs[idx]:
                m_id = row_meta['id']
                df_mats = pd.read_sql_query("SELECT id, nome FROM materias WHERE meta_id = ?", conn, params=(int(m_id),))
                
                if df_mats.empty:
                    st.info("Sem matérias cadastradas.")
                else:
                    niveis_lista = []
                    
                    q_top = "SELECT t.status, t.teoria FROM topicos t JOIN materias m ON t.materia_id = m.id WHERE m.meta_id = ?"
                    df_top_meta = pd.read_sql_query(q_top, conn, params=(int(m_id),))
                    
                    total_t = len(df_top_meta)
                    conc_t = len(df_top_meta[(df_top_meta['status'] == 'Concluído') | (df_top_meta['teoria'] == 1)])
                    parc_t = len(df_top_meta[(df_top_meta['status'] == 'Parcial') & (df_top_meta['teoria'] == 0)])
                    
                    pontos_progresso = conc_t + (parc_t * 0.5)
                    pct = (pontos_progresso / total_t * 100) if total_t > 0 else 0
                    
                    for _, r_mat in df_mats.iterrows():
                        nv = calcular_nivel_materia(r_mat['id'], conn)
                        
                        df_tm = pd.read_sql_query("SELECT status, teoria FROM topicos WHERE materia_id = ?", conn, params=(int(r_mat['id']),))
                        t_mat_total = len(df_tm)
                        t_mat_conc = len(df_tm[(df_tm['status'] == 'Concluído') | (df_tm['teoria'] == 1)])
                        pct_mat = (t_mat_conc / t_mat_total * 100) if t_mat_total > 0 else 0
                        
                        niveis_lista.append({
                            "Matéria": r_mat['nome'], 
                            "Tópicos Concluídos": f"{t_mat_conc}/{t_mat_total}",
                            "Avanço (%)": f"{pct_mat:.1f}%",
                            "Nível Domínio": nv
                        })
                    
                    df_niv = pd.DataFrame(niveis_lista)
                    media_geral = df_niv['Nível Domínio'].mean()
                    
                    col_x, col_y, col_z = st.columns(3)
                    col_x.metric("Avanço do Edital", f"{pct:.1f}%", f"{conc_t}/{total_t} tópicos")
                    col_y.metric("Domínio Médio Geral", f"{media_geral:.1f} / 10")
                    col_z.progress(min(1.0, pct / 100))
                    
                    st.subheader("🎯 Nível de Domínio e Avanço por Matéria")
                    st.dataframe(df_niv, width="stretch", hide_index=True)

                    # NOVO: horas do cronograma
                    if meta_tem_cronograma(m_id, conn):
                        st.subheader("⏱️ Horas do Cronograma")
                        df_h = pd.read_sql_query("""
                            SELECT m.nome as Matéria,
                                   ROUND(SUM(COALESCE(t.minutos_planejados, 0)) / 60.0, 1) as Previstas_h,
                                   ROUND(SUM(COALESCE(t.minutos_estudados, 0)) / 60.0, 1) as Estudadas_h
                            FROM topicos t JOIN materias m ON t.materia_id = m.id
                            WHERE m.meta_id = ? AND t.semana IS NOT NULL
                            GROUP BY m.nome ORDER BY Previstas_h DESC
                        """, conn, params=(int(m_id),))
                        tot_prev, tot_est = df_h['Previstas_h'].sum(), df_h['Estudadas_h'].sum()
                        h1, h2 = st.columns(2)
                        h1.metric("Horas estudadas", f"{tot_est:.1f} h", f"de {tot_prev:.0f} h previstas", delta_color="off")
                        h2.progress(min(1.0, tot_est / tot_prev) if tot_prev else 0.0)
                        df_h['Feito'] = (df_h['Estudadas_h'] / df_h['Previstas_h'].where(df_h['Previstas_h'] > 0)).fillna(0).clip(upper=1.0)
                        st.dataframe(
                            df_h,
                            column_config={
                                "Previstas_h": st.column_config.NumberColumn("Previstas (h)", format="%.1f"),
                                "Estudadas_h": st.column_config.NumberColumn("Estudadas (h)", format="%.1f"),
                                "Feito": st.column_config.ProgressColumn("Progresso", min_value=0.0, max_value=1.0)
                            },
                            width="stretch", hide_index=True
                        )

                        df_s = pd.read_sql_query("""
                            SELECT t.semana as Semana,
                                   ROUND(100.0 * SUM(CASE WHEN t.status = 'Concluído' THEN 1 ELSE 0 END) / COUNT(*), 0) as Concluído_pct
                            FROM topicos t JOIN materias m ON t.materia_id = m.id
                            WHERE m.meta_id = ? AND t.semana IS NOT NULL
                            GROUP BY t.semana ORDER BY t.semana
                        """, conn, params=(int(m_id),))
                        st.markdown("**% de blocos concluídos por semana**")
                        st.bar_chart(df_s.set_index('Semana'))

                    # NOVO: tempo líquido do cronômetro, pelo dia em que você estudou de verdade
                    desde = hoje() - datetime.timedelta(days=13)
                    df_t = pd.read_sql_query("""SELECT data, materia, SUM(minutos) as minutos FROM sessoes_estudo
                                                 WHERE objetivo = ? AND data >= ? GROUP BY data, materia""",
                                              conn, params=(row_meta['nome'], desde.isoformat()))
                    st.subheader("⏱️ Tempo líquido estudado (últimos 14 dias)")
                    if df_t.empty:
                        st.info("Ainda não há tempo registrado. Use ▶️ Iniciar / ⏸️ Pausar / ⏹️ Finalizar nos blocos de "
                                "'📅 Meta & Rotina do Dia'.")
                    else:
                        dias = [desde + datetime.timedelta(days=i) for i in range(14)]
                        por_dia = df_t.groupby("data")["minutos"].sum()
                        df_dia = pd.DataFrame({"Dia": pd.to_datetime([d.isoformat() for d in dias]),
                                               "Horas": [round(por_dia.get(d.isoformat(), 0) / 60, 2) for d in dias]})
                        tot14 = int(df_t["minutos"].sum())
                        tot_rev = int(df_t.loc[df_t["materia"] == MATERIA_REVISOES, "minutos"].sum())
                        k1, k2, k3 = st.columns(3)
                        k1.metric("Total em 14 dias", fmt_horas(tot14))
                        k2.metric("Média por dia", fmt_horas(round(tot14 / 14)))
                        k3.metric("Em revisões", fmt_horas(tot_rev), f"{100 * tot_rev / tot14:.0f}% do tempo" if tot14 else None,
                                  delta_color="off")
                        st.bar_chart(df_dia.set_index("Dia"), y="Horas")
                        df_mt = (df_t.groupby("materia")["minutos"].sum().sort_values(ascending=False)
                                 .reset_index().rename(columns={"materia": "Matéria", "minutos": "Minutos"}))
                        df_mt["Tempo"] = df_mt["Minutos"].apply(fmt_horas)
                        st.dataframe(df_mt[["Matéria", "Tempo"]], width="stretch", hide_index=True)

# =============================================================================
# MENU 5: GERENCIADOR
# =============================================================================
elif menu == "⚙️ Gerenciador":
    st.header("⚙️ Gerenciador do Sistema")
    
    t0, t6, t7, t1, t5 = st.tabs([
        "⚙️ Disp. de Tempo",
        "📅 Cronogramas",
        "☁️ Nuvem",
        "✍️ Cadastro manual",
        "🗑️ Excluir / Limpar Dados"
    ])

    with t6:
        st.subheader("📅 Carregar o Cronograma CFO CBMPE 2027")
        st.info("**Versão de 10/10/2026:** o rodízio de exatas, informática e idioma foi revisto para cobrir todos os itens "
                "do edital. Se você carregou o cronograma antes desta versão, recarregue-o abaixo antes de segunda-feira "
                "(12/10). O checklist do edital e as questões registradas **não** são apagados ao recarregar.")
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
                st.success(f"Cronograma recarregado: {n} blocos.")
                st.rerun()
        else:
            if st.button("🚀 Carregar cronograma", type="primary"):
                n = carregar_cronograma_cfo(conn)
                st.success(f"Cronograma carregado: {n} blocos. Veja em '🗓️ Cronograma Semanal'.")
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
        if arq_crono is not None and eh_edital:
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
                             width="stretch", hide_index=True)
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
                st.dataframe(resumo.rename("Horas").reset_index(), width="stretch", hide_index=True)
                with st.expander("Ver os blocos da semana 1"):
                    df_s1 = df_prev[df_prev["Semana"] == 1].copy()
                    df_s1["Dia"] = df_s1["Dia"].apply(lambda d: DIAS_SEMANA[int(d)])
                    st.dataframe(df_s1.drop(columns=["Semana", "Ordem"]), width="stretch", hide_index=True)
                
                c.execute("SELECT id FROM metas WHERE nome = ?", (dados_crono["objetivo"],))
                existe_obj = c.fetchone() is not None
                pode_importar = True
                if existe_obj:
                    st.warning(f"Já existe um objetivo chamado '{dados_crono['objetivo']}'. Importar APAGA o progresso dele.")
                    pode_importar = st.checkbox("Entendi. Quero substituir.", key="conf_subst_crono")
                if st.button("✅ Importar este cronograma", type="primary", disabled=not pode_importar):
                    n = carregar_cronograma(conn, dados_crono["objetivo"], dados_crono["inicio"], itens_crono,
                                            dados_crono["tipo"], substituir=existe_obj)
                    st.success(f"Cronograma importado: {n} blocos. Veja em '🗓️ Cronograma Semanal'.")
                    st.rerun()
        st.download_button("⬇️ Baixar modelo (cronograma CFO em .json)", data=gerar_json_cronograma_cfo(),
                           file_name="modelo_cronograma.json", mime="application/json")

        st.markdown("---")
        st.subheader("💾 Backup do banco de dados")
        st.write("Baixe uma cópia do seu progresso de vez em quando. Se o servidor reiniciar e os dados sumirem, "
                 "basta enviar o arquivo de volta aqui.")
        with open(DB_PATH, "rb") as f_db:
            st.download_button("⬇️ Baixar backup (.db)", data=f_db.read(),
                               file_name=f"backup_estudos_{hoje():%Y-%m-%d}.db",
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
                    preparar_edital_cfo_uma_vez.clear()
                    preparar_edital_cfo_uma_vez()
                    estado_nuvem()["ultimo_hash"] = None
                    agendar_envio()  # o backup restaurado também vai para a nuvem
                    st.success("Backup restaurado!")
                    st.rerun()

    with t7:
        st.subheader("☁️ Cópia automática na nuvem")
        est = estado_nuvem()
        cfg = _config_nuvem()
        if requests is None:
            st.error("A biblioteca 'requests' não está instalada. Confira se o arquivo requirements.txt tem a linha 'requests'.")
        elif not cfg:
            st.warning("A cópia na nuvem ainda não foi configurada. Siga o passo a passo que o Claude enviou "
                       "(criar um repositório privado no GitHub, gerar um token e colar em 'Secrets' do Streamlit).")
            st.code('[github_backup]\ntoken = "COLE_AQUI_O_TOKEN"\nrepo = "jeyverson107/dados-estudos"', language="toml")
        else:
            st.write(f"Repositório: **{cfg['repo']}** · arquivo: **{cfg['arquivo']}** · ramo: **{cfg['branch']}**")
            if est["estado"] == "ligada":
                st.success("Ligada. Cada vez que você salva algo, uma cópia vai para o GitHub em poucos segundos.")
            elif est["estado"] == "erro":
                st.error(est["erro"])
            else:
                st.info("Configurada, mas ainda não conectada. Toque em 'Reconectar'.")
            if est["ultimo_envio"]:
                st.caption(f"Último envio: {est['ultimo_envio']:%d/%m/%Y às %H:%M:%S}")
            if est["erro"] and est["estado"] == "ligada":
                st.warning(est["erro"])
        n1, n2 = st.columns(2)
        with n1:
            if st.button("🔄 Reconectar à nuvem", help="Use depois de colar ou trocar o token em Secrets."):
                restaurar_da_nuvem_ao_iniciar.clear()
                est_novo = estado_nuvem()
                est_novo.update({"estado": "desligada", "erro": "", "bloqueada": False, "sha": None, "ultimo_hash": None})
                restaurar_da_nuvem_ao_iniciar()
                st.rerun()
        with n2:
            if st.button("☁️ Enviar uma cópia agora", disabled=not (cfg and est["estado"] == "ligada")):
                try:
                    with est["lock"]:
                        est["ultimo_hash"] = None
                        _enviar_agora(est)
                    st.success("Cópia enviada!")
                except Exception as e:
                    st.error(f"Não consegui enviar: {e}")
        st.markdown("---")
        st.markdown("**Trazer os dados da nuvem para cá** (substitui os dados atuais do app pela última cópia da nuvem)")
        confirmar_baixar = st.checkbox("Entendi que os dados atuais serão substituídos.", key="conf_baixar_nuvem")
        if st.button("⬇️ Substituir pelos dados da nuvem", disabled=not (cfg and confirmar_baixar)):
            try:
                conteudo = baixar_da_nuvem(cfg)
                if not conteudo:
                    st.warning("Ainda não há cópia na nuvem.")
                else:
                    conn.close()
                    with open(DB_PATH, "wb") as f_out:
                        f_out.write(conteudo)
                    init_db()
                    preparar_edital_cfo_uma_vez.clear()
                    preparar_edital_cfo_uma_vez()
                    est.update({"estado": "ligada", "bloqueada": False, "erro": "", "ultimo_hash": None})
                    st.success("Dados trazidos da nuvem!")
                    st.rerun()
            except Exception as e:
                st.error(f"Não consegui baixar: {e}")
        st.caption("Cada envio fica guardado no histórico do repositório (aba 'Commits' no GitHub). "
                   "Se algo der errado, dá para baixar uma versão antiga de lá e restaurar pela aba '📅 Cronogramas'.")

    with t0:
        st.subheader("Configurar Disponibilidade Diária de Estudos")
        hor_atual = float(get_config("horas_estudo_dia", "3.0"))
        tur_atual = get_config("turno_estudo", "Noite")
        
        with st.form("form_disp"):
            novas_horas = st.number_input("Horas disponíveis por dia:", min_value=0.5, max_value=12.0, value=hor_atual, step=0.5)
            novo_turno = st.selectbox("Turno Principal:", ["Manhã", "Tarde", "Noite"], index=["Manhã", "Tarde", "Noite"].index(tur_atual))
            horas_fds = st.number_input("Horas de reposição sugeridas no sábado e no domingo:", min_value=0.0, max_value=12.0,
                                        value=float(get_config("horas_reposicao_fds", "3.0")), step=0.5)
            min_rev = st.number_input("Minutos para revisões em dia útil (o Bloco 3 tem 30 min):", min_value=10, max_value=240,
                                      value=int(get_config("minutos_revisao_dia", "30")), step=5)
            min_rev_fds = st.number_input("Minutos para revisões no sábado e no domingo:", min_value=0, max_value=480,
                                          value=int(get_config("minutos_revisao_fds", "60")), step=10)
            
            if st.form_submit_button("Salvar Horários"):
                set_config("horas_estudo_dia", novas_horas)
                set_config("turno_estudo", novo_turno)
                set_config("horas_reposicao_fds", horas_fds)
                set_config("minutos_revisao_dia", int(min_rev))
                set_config("minutos_revisao_fds", int(min_rev_fds))
                st.success("Configurações salvas!")
                st.rerun()

    with t1:
        st.info("**O CFO CBMPE 2027 não precisa desta aba**: objetivo, matérias, cronograma e checklist do edital já vêm prontos. "
                "Use o cadastro manual só para outros objetivos, como a faculdade. Para o CFO, marque o que estudou no "
                "'📋 Checklist' → '📚 Itens do edital'.")
        st.subheader("1. Novo objetivo")
        with st.form("f_meta"):
            n_meta = st.text_input("Nome do Objetivo (Ex: Faculdade UPE – 3º período)")
            tipo_meta = st.selectbox("Tipo", ["Faculdade", "Concurso", "Outro"])
            if st.form_submit_button("Adicionar Objetivo"):
                if n_meta.strip() != "":
                    try:
                        c = conn.cursor()
                        c.execute("INSERT INTO metas (nome, tipo) VALUES (?, ?)", (n_meta.strip(), tipo_meta))
                        conn.commit()
                        st.success(f"Objetivo '{n_meta}' adicionado!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Esse objetivo já existe.")

        st.markdown("---")
        st.subheader("2. Nova matéria")
        df_m = pd.read_sql_query("SELECT id, nome FROM metas", conn)
        if df_m.empty:
            st.caption("Cadastre um objetivo primeiro.")
        else:
            sel_m_mat = st.selectbox("Vincular ao Objetivo:", df_m['nome'].tolist(), key="sb_m_mat")
            m_id_sel = df_m[df_m['nome'] == sel_m_mat]['id'].values[0]
            if sel_m_mat == CRONO_META_NOME:
                st.warning("Este é o objetivo do CFO, que já tem todas as matérias do edital. Uma matéria nova aqui não entra "
                           "no cronograma nem no checklist do edital.")
            with st.form("f_mat"):
                n_materia = st.text_input("Nome da Matéria (Ex: Direito Civil)")
                if st.form_submit_button("Adicionar Matéria"):
                    if n_materia.strip() != "":
                        m_corrigida = normalizar_nome_materia(n_materia)
                        c = conn.cursor()
                        c.execute("INSERT INTO materias (meta_id, nome) VALUES (?, ?)", (int(m_id_sel), m_corrigida))
                        conn.commit()
                        st.success(f"Matéria '{m_corrigida}' adicionada!")
                        st.rerun()

        st.markdown("---")
        st.subheader("3. Novo tópico")
        df_mat_all = pd.read_sql_query("""
            SELECT m.id as mat_id, m.nome as mat_nome, meta.nome as meta_nome
            FROM materias m
            JOIN metas meta ON m.meta_id = meta.id
        """, conn)
        if df_mat_all.empty:
            st.caption("Cadastre uma matéria primeiro.")
        else:
            options_mat = [f"{r['meta_nome']} -> {r['mat_nome']}" for i, r in df_mat_all.iterrows()]
            sel_mat_top = st.selectbox("Selecione a Matéria:", options_mat)
            idx_mat_sel = options_mat.index(sel_mat_top)
            target_mat_id = df_mat_all.iloc[idx_mat_sel]['mat_id']
            if df_mat_all.iloc[idx_mat_sel]['meta_nome'] == CRONO_META_NOME:
                st.warning("Atenção: um tópico criado aqui numa matéria do CFO fica sem dia e sem semana, então não aparece "
                           "no cronograma nem no checklist do edital. Para o CFO, use o '📋 Checklist'.")
            with st.form("f_topico"):
                n_topico = st.text_input("Descrição do Tópico")
                if st.form_submit_button("Adicionar Tópico"):
                    if n_topico.strip() != "":
                        c = conn.cursor()
                        c.execute("INSERT INTO topicos (materia_id, nome) VALUES (?, ?)",
                                  (int(target_mat_id), n_topico.strip()))
                        conn.commit()
                        st.success("Tópico adicionado com sucesso!")
                        st.rerun()

    with t5:
        st.subheader("🗑️ Gerenciar e Excluir Dados Importados")
        st.write("Use esta opção caso tenha importado um arquivo errado ou queira refazer a carga de dados.")
        st.warning("Apagar não tem volta. Antes, baixe um backup em '📅 Cronogramas' → '⬇️ Baixar backup (.db)'. "
                   "O checklist do edital, as revisões e as questões registradas **não** são apagados por esta aba.")
        
        df_metas_del = pd.read_sql_query("SELECT id, nome FROM metas", conn)
        
        if df_metas_del.empty:
            st.info("Nenhum dado cadastrado no momento.")
        else:
            col_del1, col_del2 = st.columns(2)
            
            with col_del1:
                st.markdown("#### 1. Excluir uma Matéria Específica")
                sel_meta_d1 = st.selectbox("Selecione o Objetivo:", df_metas_del['nome'].tolist(), key="del_meta_1")
                m_id_d1 = df_metas_del[df_metas_del['nome'] == sel_meta_d1]['id'].values[0]
                
                df_mats_d1 = pd.read_sql_query("SELECT id, nome FROM materias WHERE meta_id = ?", conn, params=(int(m_id_d1),))
                
                if df_mats_d1.empty:
                    st.caption("Nenhuma matéria vinculada a este objetivo.")
                else:
                    sel_mat_del = st.selectbox("Selecione a Matéria para apagar:", df_mats_d1['nome'].tolist())
                    mat_id_del = df_mats_d1[df_mats_d1['nome'] == sel_mat_del]['id'].values[0]
                    
                    conf_d1 = st.checkbox(f"Entendi que isso apaga a matéria '{sel_mat_del}' e todos os blocos dela.", key="conf_del_1")
                    if st.button("❌ Apagar Esta Matéria e Seus Tópicos", disabled=not conf_d1):
                        c = conn.cursor()
                        c.execute("DELETE FROM materias WHERE id = ?", (int(mat_id_del),))
                        conn.commit()
                        st.success(f"Matéria '{sel_mat_del}' excluída com sucesso!")
                        st.rerun()

            with col_del2:
                st.markdown("#### 2. Apagar TODAS as Matérias de um Objetivo")
                sel_meta_d2 = st.selectbox("Selecione o Objetivo:", df_metas_del['nome'].tolist(), key="del_meta_2")
                m_id_d2 = df_metas_del[df_metas_del['nome'] == sel_meta_d2]['id'].values[0]
                
                conf_d2 = st.checkbox(f"Entendi que isso apaga TODAS as matérias e blocos de '{sel_meta_d2}'.", key="conf_del_2")
                if st.button("🚨 LIMPAR TODOS OS DADOS IMPORTADOS DESTE OBJETIVO", type="primary", disabled=not conf_d2):
                    c = conn.cursor()
                    c.execute("DELETE FROM materias WHERE meta_id = ?", (int(m_id_d2),))
                    conn.commit()
                    st.success(f"Todas as matérias e tópicos de '{sel_meta_d2}' foram apagados. Você pode importar novamente.")
                    st.rerun()

conn.close()