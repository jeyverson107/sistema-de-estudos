import streamlit as st
import pandas as pd
import datetime
import sqlite3

st.set_page_config(page_title="Sistema Versátil de Estudos", layout="wide", page_icon="🛡️")

# -----------------------------------------------------------------------------
# BANCO DE DADOS DINÂMICO (SQLite)
# -----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect("estudos_versatil.db")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Tabela de Objetivos (ex: PMPE, 3º Período UPE, etc.)
    c.execute('''CREATE TABLE IF NOT EXISTS metas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT UNIQUE,
                    tipo TEXT,
                    ativa INTEGER DEFAULT 1
                )''')
    # Tabela de Matérias vinculadas a uma Meta
    c.execute('''CREATE TABLE IF NOT EXISTS materias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meta_id INTEGER,
                    nome TEXT,
                    FOREIGN KEY(meta_id) REFERENCES metas(id) ON DELETE CASCADE
                )''')
    # Tabela de Tópicos vinculados a uma Matéria
    c.execute('''CREATE TABLE IF NOT EXISTS topicos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    materia_id INTEGER,
                    nome TEXT,
                    concluido INTEGER DEFAULT 0,
                    FOREIGN KEY(materia_id) REFERENCES materias(id) ON DELETE CASCADE
                )''')
    # Tabela de Exercícios
    c.execute('''CREATE TABLE IF NOT EXISTS exercicios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT,
                    topico_id INTEGER,
                    acertos INTEGER,
                    erros INTEGER,
                    FOREIGN KEY(topico_id) REFERENCES topicos(id) ON DELETE CASCADE
                )''')
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------------
# LÓGICA DE ESCALA DE SERVIÇO 24x72h
# -----------------------------------------------------------------------------
def calcular_fase_escala(data_atual, data_base):
    dias_passados = (data_atual - data_base).days
    fase = dias_passados % 4
    if fase == 0:
        return "Dia 1: PLANTÃO (24h)", 0.0, "Descanso total dos livros. Foco no serviço."
    elif fase == 1:
        return "Dia 2: FOLGA 1 (Pós-Plantão)", 1.5, "Revisão leve de 1h30m (Revisar erros e conceitos)."
    elif fase == 2:
        return "Dia 3: FOLGA 2 (Estudo Intenso)", 3.0, "3h de estudo focado (Teoria + Bateria de Questões)."
    else:
        return "Dia 4: FOLGA 3 (Estudo Intenso)", 3.0, "3h de estudo focado (Resolução de Questões + TAF)."

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🛡️ Sistema Versátil de Gestão de Estudos")

# Menu Lateral
menu = st.sidebar.radio("Navegação", [
    "📅 Meta do Dia", 
    "📝 Registrar Questões", 
    "📋 Checklist de Conteúdos", 
    "📊 Relatórios de Evolução", 
    "⚙️ Gerenciador de Objetivos e Matérias"
])

conn = get_db()

# --- MENU 1: META DO DIA ---
if menu == "📅 Meta do Dia":
    st.header("🎯 Planejamento Diário")
    
    st.sidebar.subheader("⚙️ Configurar Escala")
    data_base_input = st.sidebar.date_input("Data do Último Plantão", datetime.date(2026, 8, 4))
    
    hoje = datetime.date.today()
    fase_nome, horas_meta, orientacao = calcular_fase_escala(hoje, data_base_input)
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Data Atual:** {hoje.strftime('%d/%m/%Y')}")
        st.metric("Status da Escala 24x72h", fase_nome)
    with col2:
        st.metric("Meta de Estudo Recomendada", f"{horas_meta} horas")
        st.write(f"**Diretriz:** {orientacao}")
        
    st.markdown("---")
    st.subheader("📌 Objetivos Ativos no Momento")
    df_metas_ativas = pd.read_sql_query("SELECT nome, tipo FROM metas WHERE ativa = 1", conn)
    if not df_metas_ativas.empty:
        st.dataframe(df_metas_ativas, hide_index=True, use_container_width=True)
    else:
        st.warning("Nenhum objetivo ativo. Cadastre um no menu '⚙️ Gerenciador'.")

# --- MENU 2: REGISTRAR QUESTÕES ---
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
            
            df_top = pd.read_sql_query("SELECT id, nome FROM topicos WHERE materia_id = ?", conn, params=(int(mat_id),))
            
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
                                  (datetime.date.today().strftime('%Y-%m-%d'), int(topico_id), acertos, erros))
                        conn.commit()
                        st.success("Registro de exercícios salvo com sucesso!")

# --- MENU 3: CHECKLIST DE CONTEÚDOS ---
elif menu == "📋 Checklist de Conteúdos":
    st.header("📋 Checklist de Conteúdos")
    
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.info("Nenhum objetivo cadastrado.")
    else:
        meta_sel = st.selectbox("Filtrar por Objetivo", df_metas['nome'].tolist())
        meta_id = df_metas[df_metas['nome'] == meta_sel]['id'].values[0]
        
        query = """
            SELECT t.id, m.nome as Materia, t.nome as Topico, t.concluido 
            FROM topicos t
            JOIN materias m ON t.materia_id = m.id
            WHERE m.meta_id = ?
        """
        df_topicos = pd.read_sql_query(query, conn, params=(int(meta_id),))
        
        if df_topicos.empty:
            st.info("Nenhum tópico cadastrado para este objetivo.")
        else:
            df_topicos['concluido'] = df_topicos['concluido'].astype(bool)
            
            edited_df = st.data_editor(
                df_topicos[['id', 'Materia', 'Topico', 'concluido']],
                column_config={"concluido": st.column_config.CheckboxColumn("Estudado/OK")},
                disabled=["id", "Materia", "Topico"],
                hide_index=True,
                use_container_width=True
            )
            
            if st.button("Salvar Atualizações de Progresso"):
                c = conn.cursor()
                for idx, row in edited_df.iterrows():
                    c.execute("UPDATE topicos SET concluido = ? WHERE id = ?", (1 if row['concluido'] else 0, int(row['id'])))
                conn.commit()
                st.success("Progresso atualizado!")
                st.rerun()

# --- MENU 4: RELATÓRIOS ---
elif menu == "📊 Relatórios de Evolução":
    st.header("📊 Relatório de Desempenho e Cobertura")
    
    df_metas = pd.read_sql_query("SELECT id, nome, tipo FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.warning("Nenhum objetivo ativo para gerar relatórios.")
    else:
        tabs = st.tabs(df_metas['nome'].tolist())
        
        for idx, row_meta in df_metas.iterrows():
            with tabs[idx]:
                m_id = row_meta['id']
                
                # Progresso do Edital/PPC
                q_top = """
                    SELECT t.id, t.concluido 
                    FROM topicos t 
                    JOIN materias m ON t.materia_id = m.id 
                    WHERE m.meta_id = ?
                """
                df_top_meta = pd.read_sql_query(q_top, conn, params=(int(m_id),))
                total_t = len(df_top_meta)
                conc_t = len(df_top_meta[df_top_meta['concluido'] == 1])
                pct = (conc_t / total_t * 100) if total_t > 0 else 0
                
                col_x, col_y = st.columns(2)
                col_x.metric("Cobertura do Conteúdo", f"{pct:.1f}%", f"{conc_t}/{total_t} tópicos concluídos")
                col_y.progress(pct / 100)
                
                st.markdown("---")
                # Questões
                q_ex = """
                    SELECT m.nome as Materia, e.acertos, e.erros 
                    FROM exercicios e
                    JOIN topicos t ON e.topico_id = t.id
                    JOIN materias m ON t.materia_id = m.id
                    WHERE m.meta_id = ?
                """
                df_ex_meta = pd.read_sql_query(q_ex, conn, params=(int(m_id),))
                
                if not df_ex_meta.empty:
                    st.subheader("🎯 Desempenho em Resolução de Questões")
                    tot_a = df_ex_meta['acertos'].sum()
                    tot_e = df_ex_meta['erros'].sum()
                    tot_q = tot_a + tot_e
                    taxa = (tot_a / tot_q * 100) if tot_q > 0 else 0
                    
                    st.write(f"**Total de Questões Feitas:** {tot_q} | **Aproveitamento Geral:** {taxa:.1f}%")
                    
                    grp = df_ex_meta.groupby('Materia').sum().reset_index()
                    grp['Total'] = grp['acertos'] + grp['erros']
                    grp['% Acertos'] = (grp['acertos'] / grp['Total'] * 100).round(1)
                    st.dataframe(grp[['Materia', 'Total', 'acertos', 'erros', '% Acertos']], hide_index=True, use_container_width=True)
                else:
                    st.info("Nenhum exercício registrado para este objetivo ainda.")

# --- MENU 5: GERENCIADOR (ADICIONAR/REMOVER METAS, MATÉRIAS E TÓPICOS) ---
elif menu == "⚙️ Gerenciador de Objetivos e Matérias":
    st.header("⚙️ Gerenciador do Sistema")
    st.write("Adicione ou remova concursos, semestres de faculdade, matérias e tópicos individualmente.")
    
    t1, t2, t3 = st.tabs(["1. Objetivos (Concursos/Semestres)", "2. Matérias", "3. Tópicos de Conteúdo"])
    
    # Aba 1: Gerenciar Objetivos
    with t1:
        st.subheader("Cadastrar Novo Objetivo")
        with st.form("f_meta"):
            n_meta = st.text_input("Nome do Objetivo (Ex: Concurso PMPE, 4º Período UPE)")
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
        
        st.subheader("Objetivos Cadastrados")
        df_m = pd.read_sql_query("SELECT id, nome, tipo, ativa FROM metas", conn)
        if not df_m.empty:
            for i, r in df_m.iterrows():
                col_m1, col_m2 = st.columns([3, 1])
                col_m1.write(f"**{r['nome']}** ({r['tipo']})")
                if col_m2.button(f"Excluir '{r['nome']}'", key=f"del_m_{r['id']}"):
                    c = conn.cursor()
                    c.execute("DELETE FROM metas WHERE id = ?", (r['id'],))
                    conn.commit()
                    st.success("Excluído com sucesso!")
                    st.rerun()

    # Aba 2: Gerenciar Matérias
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
                        c = conn.cursor()
                        c.execute("INSERT INTO materias (meta_id, nome) VALUES (?, ?)", (int(m_id_sel), n_materia.strip()))
                        conn.commit()
                        st.success(f"Matéria '{n_materia}' adicionada!")
                        st.rerun()

    # Aba 3: Gerenciar Tópicos
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
                n_topico = st.text_input("Descrição do Tópico (Ex: Atos Administrativos - Espécies)")
                if st.form_submit_button("Adicionar Tópico"):
                    if n_topico.strip() != "":
                        c = conn.cursor()
                        c.execute("INSERT INTO topicos (materia_id, nome) VALUES (?, ?)", (int(target_mat_id), n_topico.strip()))
                        conn.commit()
                        st.success("Tópico adicionado com sucesso!")
                        st.rerun()

conn.close()
