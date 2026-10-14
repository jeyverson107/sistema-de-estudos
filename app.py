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
    carregar_orientacoes_padrao(c)

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
        c.execute("UPDATE topicos SET status = ?, teoria = ?, resumo = MAX(resumo, ?), minutos_estudados = ? WHERE id = ?",
                  (status, teoria, resumo, int(minutos), int(topico_id)))
    conn.commit()

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🛡️ Sistema Unificado de Gestão de Estudos")

menu = st.sidebar.radio("Navegação", [
    "📅 Meta & Rotina do Dia",
    "🧭 Planejar Estudos",
    "🗓️ Cronograma Semanal",
    "📋 Checklist & Acompanhamento",
    "🎯 Simulado do que já estudei",
    "📝 Registrar Questões", 
    "📊 Dashboard de Evolução", 
    "⚙️ Gerenciador"
])

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

conn = get_db()
ajuste_estatuto_14_10(conn)

# =============================================================================
# MENU 1: META & ROTINA DO DIA
# =============================================================================
if menu == "📅 Meta & Rotina do Dia":
    st.header("🎯 Sugestão Diária de Estudo e Rotina Policial")
    
    escalado = st.checkbox("🚨 Estarei Escalado Hoje / Plantão Extra (Suspender estudos hoje)", value=False)
    
    if escalado:
        st.warning("⚠️ **Modo Plantão/Escala Ativado:** O ciclo de estudos foi pausado para hoje. Bons serviços no plantão!")
    else:
        horas_disp = float(get_config("horas_estudo_dia", "3.0"))
        turno_pref = get_config("turno_estudo", "Noite")
        
        st.info(f"💡 **Disponibilidade Hoje:** {horas_disp} horas no turno da **{turno_pref}**.")
        
        df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
        
        if df_metas.empty:
            st.warning("Nenum objetivo cadastrado. Cadastre um em '⚙️ Gerenciador'.")
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
                    st.subheader(f"📆 Semana {semana_hoje} · {DIAS_SEMANA[dia_hoje]} – blocos de hoje")
                    df_hoje = pd.read_sql_query("""
                        SELECT t.id, t.nome, t.bloco, t.minutos_planejados, t.minutos_estudados, t.status, m.nome as materia
                        FROM topicos t JOIN materias m ON t.materia_id = m.id
                        WHERE m.meta_id = ? AND t.semana = ? AND t.dia = ?
                        ORDER BY t.ordem
                    """, conn, params=(int(meta_id_rotina), int(semana_hoje), int(dia_hoje)))
                    if df_hoje.empty:
                        st.info("Nenhum bloco previsto para hoje.")
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
                                    salvar_orientacao(conn, row['materia'], row['nome'], novo_txt)
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
                                    salvar_status_topico(conn, topico_id, "Concluído", minutos)
                                    set_timer_stop(topico_id)
                                    st.rerun()
                            with col_b:
                                if st.button("⏳ Fiz só uma parte", key=f"cr_parc_{topico_id}"):
                                    salvar_status_topico(conn, topico_id, "Parcial", minutos_ja + minutos_cronometrados)
                                    set_timer_stop(topico_id)
                                    st.rerun()

                            if timer_data['status'] == 'RODANDO':
                                time.sleep(1)
                                st.rerun()
                conn.close()
                st.stop()

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
                st.success("Semana salva! O Dashboard e o Checklist já foram atualizados.")
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

elif menu == "📋 Checklist & Acompanhamento":
    st.header("📋 Checklist de Conteúdos por Matéria")
    
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.info("Nenhum objetivo cadastrado.")
    else:
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            meta_sel = st.selectbox("1. Selecione o Objetivo", df_metas['nome'].tolist())
            meta_id = df_metas[df_metas['nome'] == meta_sel]['id'].values[0]
        
        df_mat = pd.read_sql_query("SELECT id, nome FROM materias WHERE meta_id = ?", conn, params=(int(meta_id),))
        
        if df_mat.empty:
            st.warning("Nenhuma matéria cadastrada para este objetivo.")
        else:
            with col_m2:
                mat_sel = st.selectbox("2. Filtrar por Matéria", df_mat['nome'].tolist())
                mat_id = df_mat[df_mat['nome'] == mat_sel]['id'].values[0]
            
            nivel_atual = calcular_nivel_materia(mat_id, conn)
            st.info(f"📊 **Nível de Domínio Calculado em {mat_sel}:** `{nivel_atual} / 10.0`")
            
            query = """
                SELECT id, nome as Topico, teoria as Videoaula_PDF, resumo as Resumo_Mapa, status as Status
                FROM topicos
                WHERE materia_id = ?
            """
            df_topicos = pd.read_sql_query(query, conn, params=(int(mat_id),))
            
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
                        "Status": st.column_config.SelectboxColumn(
                            "Status de Conclusão",
                            options=["Pendente", "Parcial", "Concluído"],
                            required=True
                        )
                    },
                    disabled=["id", "Topico"],
                    hide_index=True,
                    use_container_width=True
                )
                
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

                        c.execute("""
                            UPDATE topicos 
                            SET teoria = ?, resumo = ?, status = ? 
                            WHERE id = ?
                        """, (is_teoria, is_resumo, status_str, int(row['id'])))
                    conn.commit()
                    st.success("Progresso salvo e sincronizado com o Dashboard de Evolução!")
                    st.rerun()

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
                       "em '📅 Meta & Rotina do Dia', '🗓️ Cronograma Semanal' ou '📋 Checklist'.")
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
                
                with st.form("form_ex"):
                    col_a, col_b = st.columns(2)
                    with col_a: acertos = st.number_input("Número de Acertos", min_value=0, value=10)
                    with col_b: erros = st.number_input("Número de Erros", min_value=0, value=2)
                    
                    if st.form_submit_button("Salvar Desempenho"):
                        c = conn.cursor()
                        c.execute("INSERT INTO exercicios (data, topico_id, acertos, erros) VALUES (?, ?, ?, ?)",
                                  (hoje_local().strftime('%Y-%m-%d'), int(topico_id), acertos, erros))
                        conn.commit()
                        st.success("Exercícios registrados com sucesso!")
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
                    st.dataframe(df_niv, use_container_width=True, hide_index=True)

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
                            use_container_width=True, hide_index=True
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

# =============================================================================
# MENU 5: GERENCIADOR
# =============================================================================
elif menu == "⚙️ Gerenciador":
    st.header("⚙️ Gerenciador do Sistema")
    
    t0, t1, t2, t3, t6, t5 = st.tabs([
        "⚙️ Disp. de Tempo",
        "1. Objetivos",
        "2. Matérias",
        "3. Tópicos",
        "📅 Cronogramas",
        "🗑️ Excluir / Limpar Dados"
    ])

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
                    st.success("Backup restaurado!")
                    st.rerun()

    with t0:
        st.subheader("Configurar Disponibilidade Diária de Estudos")
        hor_atual = float(get_config("horas_estudo_dia", "3.0"))
        tur_atual = get_config("turno_estudo", "Noite")
        
        with st.form("form_disp"):
            novas_horas = st.number_input("Horas disponíveis por dia:", min_value=0.5, max_value=12.0, value=hor_atual, step=0.5)
            novo_turno = st.selectbox("Turno Principal:", ["Manhã", "Tarde", "Noite"], index=["Manhã", "Tarde", "Noite"].index(tur_atual))
            
            if st.form_submit_button("Salvar Horários"):
                set_config("horas_estudo_dia", novas_horas)
                set_config("turno_estudo", novo_turno)
                st.success("Configurações salvas!")
                st.rerun()

    with t1:
        st.subheader("Cadastrar Novo Objetivo")
        with st.form("f_meta"):
            n_meta = st.text_input("Nome do Objetivo (Ex: Concurso PMPE, Faculdade UPE)")
            tipo_meta = st.selectbox("Tipo", ["Concurso", "Faculdade", "Outro"])
            if st.form_submit_button("Adicionar Objetivo"):
                if n_meta.strip() != "":
                    try:
                        c = conn.cursor()
                        c.execute("INSERT INTO metas (nome, tipo) VALUES (?, ?)", (n_meta.strip(), tipo_meta))
                        conn.commit()
                        st.success(f"Objetivo '{n_meta}' adicionado!")
                        st.rerun()
                    except:
                        st.error("Esse objetivo já existe.")

    with t2:
        df_m = pd.read_sql_query("SELECT id, nome FROM metas", conn)
        if df_m.empty:
            st.warning("Cadastre um objetivo primeiro.")
        else:
            st.subheader("Cadastrar Nova Matéria")
            sel_m_mat = st.selectbox("Vincular ao Objetivo:", df_m['nome'].tolist(), key="sb_m_mat")
            m_id_sel = df_m[df_m['nome'] == sel_m_mat]['id'].values[0]
            
            with st.form("f_mat"):
                n_materia = st.text_input("Nome da Matéria (Ex: Direito Administrativo)")
                if st.form_submit_button("Adicionar Matéria"):
                    if n_materia.strip() != "":
                        m_corrigida = normalizar_nome_materia(n_materia)
                        c = conn.cursor()
                        c.execute("INSERT INTO materias (meta_id, nome) VALUES (?, ?)", (int(m_id_sel), m_corrigida))
                        conn.commit()
                        st.success(f"Matéria '{m_corrigida}' adicionada!")
                        st.rerun()

    with t3:
        df_mat_all = pd.read_sql_query("""
            SELECT m.id as mat_id, m.nome as mat_nome, meta.nome as meta_nome 
            FROM materias m 
            JOIN metas meta ON m.meta_id = meta.id
        """, conn)
        
        if df_mat_all.empty:
            st.warning("Cadastre matérias primeiro.")
        else:
            st.subheader("Cadastrar Tópico Individual")
            options_mat = [f"{r['meta_nome']} -> {r['mat_nome']}" for i, r in df_mat_all.iterrows()]
            sel_mat_top = st.selectbox("Selecione a Matéria:", options_mat)
            idx_mat_sel = options_mat.index(sel_mat_top)
            target_mat_id = df_mat_all.iloc[idx_mat_sel]['mat_id']
            
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
                    
                    if st.button("❌ Apagar Esta Matéria e Seus Tópicos"):
                        c = conn.cursor()
                        c.execute("DELETE FROM materias WHERE id = ?", (int(mat_id_del),))
                        conn.commit()
                        st.success(f"Matéria '{sel_mat_del}' excluída com sucesso!")
                        st.rerun()

            with col_del2:
                st.markdown("#### 2. Apagar TODAS as Matérias de um Objetivo")
                sel_meta_d2 = st.selectbox("Selecione o Objetivo:", df_metas_del['nome'].tolist(), key="del_meta_2")
                m_id_d2 = df_metas_del[df_metas_del['nome'] == sel_meta_d2]['id'].values[0]
                
                if st.button("🚨 LIMPAR TODOS OS DADOS IMPORTADOS DESTE OBJETIVO", type="primary"):
                    c = conn.cursor()
                    c.execute("DELETE FROM materias WHERE meta_id = ?", (int(m_id_d2),))
                    conn.commit()
                    st.success(f"Todas as matérias e tópicos de '{sel_meta_d2}' foram apagados. Você pode importar novamente.")
                    st.rerun()

conn.close()