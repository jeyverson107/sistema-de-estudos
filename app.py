import streamlit as st
import pandas as pd
import datetime
import sqlite3

st.set_page_config(page_title="Sistema de Estudos & Carreira", layout="wide", page_icon="🛡️")

# -----------------------------------------------------------------------------
# BANCO DE DADOS DINÂMICO (SQLite)
# -----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect("estudos_master.db")
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
                    nivel INTEGER DEFAULT 0,
                    concluido INTEGER DEFAULT 0,
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
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------------
# LÓGICA DE ESCALAS DE TRABALHO
# -----------------------------------------------------------------------------
def calcular_fase_escala_24x72(data_atual, data_base):
    dias_passados = (data_atual - data_base).days
    fase = dias_passados % 4
    if fase == 0:
        return "Dia 1: PLANTÃO (24h)", 0.0, "Descanso total dos livros. Foco no serviço público."
    elif fase == 1:
        return "Dia 2: FOLGA 1 (Pós-Plantão)", 1.5, "Revisão leve de 1h30m (Revisar erros e conceitos)."
    elif fase == 2:
        return "Dia 3: FOLGA 2 (Estudo Intenso)", 3.5, "3h30m de estudo focado (Teoria + Questões)."
    else:
        return "Dia 4: FOLGA 3 (Estudo Intenso)", 3.5, "3h30m de estudo focado (Questões + TAF/Simulado)."

def calcular_rotina_administrativo(data_atual, hora_inicio, hora_fim):
    dia_semana = data_atual.weekday()
    if dia_semana < 5:
        return (
            f"Expediente Administrativo ({hora_inicio.strftime('%H:%M')} às {hora_fim.strftime('%H:%M')})",
            2.5,
            "Dia de Trabalho. Meta de 2h30m no turno da noite ou horários vagos."
        )
    else:
        return (
            "Final de Semana (Livre)",
            4.5,
            "Dia Livre de Expediente. Aproveite para 4h30m de estudo focado."
        )

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🛡️ Sistema Unificado de Gestão de Estudos")

menu = st.sidebar.radio("Navegação", [
    "📅 Meta & Rotina do Dia", 
    "📝 Registrar Questões", 
    "📋 Checklist & Acompanhamento", 
    "📊 Dashboard de Evolução", 
    "⚙️ Gerenciador & Importador Excel"
])

conn = get_db()

# --- MENU 1: META DO DIA ---
if menu == "📅 Meta & Rotina do Dia":
    st.header("🎯 Planejamento Diário e Escala de Trabalho")
    
    st.sidebar.subheader("⚙️ Configurar Regime de Trabalho")
    tipo_regime = st.sidebar.selectbox("Selecione seu Regime Atual", ["Plantão (24x72h)", "Administrativo (Seg a Sex)"])
    
    hoje = datetime.date.today()
    
    if tipo_regime == "Plantão (24x72h)":
        data_base_input = st.sidebar.date_input("Data do Último Plantão", datetime.date(2026, 8, 4))
        fase_nome, horas_meta, orientacao = calcular_fase_escala_24x72(hoje, data_base_input)
    else:
        hora_in = st.sidebar.time_input("Início do Expediente", datetime.time(8, 0))
        hora_fi = st.sidebar.time_input("Fim do Expediente", datetime.time(15, 0))
        fase_nome, horas_meta, orientacao = calcular_rotina_administrativo(hoje, hora_in, hora_fi)
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Data Atual:** {hoje.strftime('%d/%m/%Y')}")
        st.metric("Regime / Status Atual", fase_nome)
    with col2:
        st.metric("Meta de Estudo Sugerida", f"{horas_meta} horas")
        st.write(f"**Diretriz:** {orientacao}")
        
    st.markdown("---")
    st.subheader("📌 Objetivos Cadastrados e Ativos")
    df_metas_ativas = pd.read_sql_query("SELECT nome, tipo FROM metas WHERE ativa = 1", conn)
    if not df_metas_ativas.empty:
        st.dataframe(df_metas_ativas, hide_index=True, use_container_width=True)
    else:
        st.warning("Nenhum objetivo ativo. Cadastre ou importe no menu '⚙️ Gerenciador'.")

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
elif menu == "📋 Checklist & Acompanhamento":
    st.header("📋 Checklist Tríplice de Conteúdos")
    
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.info("Nenhum objetivo cadastrado.")
    else:
        meta_sel = st.selectbox("Filtrar por Objetivo", df_metas['nome'].tolist())
        meta_id = df_metas[df_metas['nome'] == meta_sel]['id'].values[0]
        
        query = """
            SELECT t.id, m.nome as Materia, t.nome as Topico, 
                   t.teoria as Videoaula_PDF, t.resumo as Resumo_Mapa, 
                   t.nivel as Nivel_0_a_10, t.concluido as Concluido
            FROM topicos t
            JOIN materias m ON t.materia_id = m.id
            WHERE m.meta_id = ?
        """
        df_topicos = pd.read_sql_query(query, conn, params=(int(meta_id),))
        
        if df_topicos.empty:
            st.info("Nenhum tópico cadastrado para este objetivo.")
        else:
            df_topicos['Videoaula_PDF'] = df_topicos['Videoaula_PDF'].astype(bool)
            df_topicos['Resumo_Mapa'] = df_topicos['Resumo_Mapa'].astype(bool)
            df_topicos['Concluido'] = df_topicos['Concluido'].astype(bool)
            
            edited_df = st.data_editor(
                df_topicos[['id', 'Materia', 'Topico', 'Videoaula_PDF', 'Resumo_Mapa', 'Nivel_0_a_10', 'Concluido']],
                column_config={
                    "Videoaula_PDF": st.column_config.CheckboxColumn("Videoaula/PDF"),
                    "Resumo_Mapa": st.column_config.CheckboxColumn("Resumo/Mapa"),
                    "Concluido": st.column_config.CheckboxColumn("Concluído"),
                    "Nivel_0_a_10": st.column_config.NumberColumn("Nível (0-10)", min_value=0, max_value=10, step=1)
                },
                disabled=["id", "Materia", "Topico"],
                hide_index=True,
                use_container_width=True
            )
            
            if st.button("💾 Salvar Alterações no Checklist"):
                c = conn.cursor()
                for idx, row in edited_df.iterrows():
                    c.execute("""
                        UPDATE topicos 
                        SET teoria = ?, resumo = ?, nivel = ?, concluido = ? 
                        WHERE id = ?
                    """, (
                        1 if row['Videoaula_PDF'] else 0,
                        1 if row['Resumo_Mapa'] else 0,
                        int(row['Nivel_0_a_10']),
                        1 if row['Concluido'] else 0,
                        int(row['id'])
                    ))
                conn.commit()
                st.success("Progresso salvo com sucesso!")
                st.rerun()

# --- MENU 4: RELATÓRIOS ---
elif menu == "📊 Dashboard de Evolução":
    st.header("📊 Dashboard Geral de Desempenho")
    
    df_metas = pd.read_sql_query("SELECT id, nome, tipo FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.warning("Nenhum objetivo ativo para gerar relatórios.")
    else:
        tabs = st.tabs(df_metas['nome'].tolist())
        
        for idx, row_meta in df_metas.iterrows():
            with tabs[idx]:
                m_id = row_meta['id']
                
                q_top = """
                    SELECT t.id, t.nivel, t.concluido 
                    FROM topicos t 
                    JOIN materias m ON t.materia_id = m.id 
                    WHERE m.meta_id = ?
                """
                df_top_meta = pd.read_sql_query(q_top, conn, params=(int(m_id),))
                total_t = len(df_top_meta)
                conc_t = len(df_top_meta[df_top_meta['concluido'] == 1])
                pct = (conc_t / total_t * 100) if total_t > 0 else 0
                media_nivel = df_top_meta['nivel'].mean() if total_t > 0 else 0
                
                col_x, col_y, col_z = st.columns(3)
                col_x.metric("Avanço Geral do Edital", f"{pct:.1f}%", f"{conc_t}/{total_t} concluídos")
                col_y.metric("Nível Médio de Domínio", f"{media_nivel:.1f} / 10")
                col_z.progress(pct / 100)
                
                st.markdown("---")
                q_ex = """
                    SELECT m.nome as Materia, e.acertos, e.erros 
                    FROM exercicios e
                    JOIN topicos t ON e.topico_id = t.id
                    JOIN materias m ON t.materia_id = m.id
                    WHERE m.meta_id = ?
                """
                df_ex_meta = pd.read_sql_query(q_ex, conn, params=(int(m_id),))
                
                if not df_ex_meta.empty:
                    st.subheader("🎯 Resumo de Questões Resolvidas")
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

# --- MENU 5: GERENCIADOR COMPLETO & IMPORTADOR ---
elif menu == "⚙️ Gerenciador & Importador Excel":
    st.header("⚙️ Gerenciador do Sistema & Leitor de Planilhas")
    
    t1, t2, t3, t4 = st.tabs([
        "1. Objetivos", 
        "2. Matérias", 
        "3. Tópicos", 
        "4. 📥 Importar Planilha Completa"
    ])
    
    # Aba 1: Objetivos
    with t1:
        st.subheader("Cadastrar Novo Objetivo")
        with st.form("f_meta"):
            n_meta = st.text_input("Nome do Objetivo (Ex: Concurso PMPE, Faculdade UPE - 3º Período)")
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
        df_m = pd.read_sql_query("SELECT id, nome, tipo FROM metas", conn)
        if not df_m.empty:
            for i, r in df_m.iterrows():
                col_m1, col_m2 = st.columns([3, 1])
                col_m1.write(f"📌 **{r['nome']}** ({r['tipo']})")
                if col_m2.button(f"🗑️ Excluir Objetivo", key=f"del_m_{r['id']}"):
                    c = conn.cursor()
                    c.execute("DELETE FROM metas WHERE id = ?", (r['id'],))
                    conn.commit()
                    st.success("Objetivo excluído!")
                    st.rerun()

    # Aba 2: Matérias
    with t2:
        df_m = pd.read_sql_query("SELECT id, nome FROM metas", conn)
        if df_m.empty:
            st.warning("Cadastre um objetivo primeiro.")
        else:
            st.subheader("Cadastrar Nova Matéria")
            sel_m_mat = st.selectbox("Vincular ao Objetivo:", df_m['nome'].tolist(), key="sb_m_mat")
            m_id_sel = df_m[df_m['nome'] == sel_m_mat]['id'].values[0]
            
            with st.form("f_mat"):
                n_materia = st.text_input("Nome da Matéria (Ex: Direito Administrativo, Direito Civil II)")
                if st.form_submit_button("Adicionar Matéria"):
                    if n_materia.strip() != "":
                        c = conn.cursor()
                        c.execute("INSERT INTO materias (meta_id, nome) VALUES (?, ?)", (int(m_id_sel), n_materia.strip()))
                        conn.commit()
                        st.success(f"Matéria '{n_materia}' adicionada!")
                        st.rerun()

            st.markdown("---")
            st.subheader("Matérias Cadastradas")
            df_mat_list = pd.read_sql_query("""
                SELECT m.id, m.nome as materia, meta.nome as objetivo 
                FROM materias m 
                JOIN metas meta ON m.meta_id = meta.id
            """, conn)
            
            if not df_mat_list.empty:
                for i, r in df_mat_list.iterrows():
                    col_a, col_b = st.columns([3, 1])
                    col_a.write(f"📖 **{r['materia']}** *(Objetivo: {r['objetivo']})*")
                    if col_b.button("🗑️ Excluir Matéria", key=f"del_mat_{r['id']}"):
                        c = conn.cursor()
                        c.execute("DELETE FROM materias WHERE id = ?", (r['id'],))
                        conn.commit()
                        st.success("Matéria excluída!")
                        st.rerun()

    # Aba 3: Tópicos
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
                n_nivel = st.slider("Nível Atual de Domínio (0-10)", 0, 10, 5)
                if st.form_submit_button("Adicionar Tópico"):
                    if n_topico.strip() != "":
                        c = conn.cursor()
                        c.execute("INSERT INTO topicos (materia_id, nome, nivel) VALUES (?, ?, ?)", 
                                  (int(target_mat_id), n_topico.strip(), n_nivel))
                        conn.commit()
                        st.success("Tópico adicionado com sucesso!")
                        st.rerun()

            st.markdown("---")
            st.subheader("Tópicos Cadastrados")
            df_top_list = pd.read_sql_query("""
                SELECT t.id, t.nome as topico, m.nome as materia, t.nivel 
                FROM topicos t 
                JOIN materias m ON t.materia_id = m.id
            """, conn)
            
            if not df_top_list.empty:
                for i, r in df_top_list.iterrows():
                    col_a, col_b = st.columns([3, 1])
                    col_a.write(f"📝 **{r['topico']}** *(Matéria: {r['materia']} | Nível: {r['nivel']}/10)*")
                    if col_b.button("🗑️ Excluir Tópico", key=f"del_top_{r['id']}"):
                        c = conn.cursor()
                        c.execute("DELETE FROM topicos WHERE id = ?", (r['id'],))
                        conn.commit()
                        st.success("Tópico excluído!")
                        st.rerun()

    # Aba 4: Importador da Sua Planilha
    with t4:
        st.subheader("📥 Importar Planilha Completa (`CRONOGRAMA DE ESTUDO.xlsx`)")
        st.write("O leitor abaixo consome automaticamente todas as abas da sua planilha Excel de uma só vez!")
        
        df_m = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
        
        if df_m.empty:
            st.warning("Cadastre primeiro um Objetivo na Aba 1 (ex: 'Concurso PMPE') antes de importar a planilha.")
        else:
            meta_excel_sel = st.selectbox("Vincular os dados desta planilha ao Objetivo:", df_m['nome'].tolist())
            meta_excel_id = df_m[df_m['nome'] == meta_excel_sel]['id'].values[0]
            
            uploaded_file = st.file_uploader("Selecione sua planilha `CRONOGRAMA DE ESTUDO.xlsx`", type=["xlsx"])
            
            if uploaded_file is not None:
                try:
                    xls = pd.ExcelFile(uploaded_file)
                    st.success(f"Planilha reconhecida com sucesso! Abas encontradas: {', '.join(xls.sheet_names)}")
                    
                    if st.button("🚀 Processar e Importar Tudo para o Banco de Dados"):
                        c = conn.cursor()
                        total_m_count = 0
                        total_t_count = 0
                        
                        for sheet in xls.sheet_names:
                            if sheet.upper() == "DASHBOARD":
                                continue
                            
                            df_sheet = pd.read_excel(uploaded_file, sheet_name=sheet)
                            mat_nome = sheet.strip().upper()
                            
                            c.execute("SELECT id FROM materias WHERE meta_id = ? AND UPPER(nome) = ?", (int(meta_excel_id), mat_nome))
                            res_mat = c.fetchone()
                            if res_mat:
                                mat_id = res_mat[0]
                            else:
                                c.execute("INSERT INTO materias (meta_id, nome) VALUES (?, ?)", (int(meta_excel_id), mat_nome))
                                mat_id = c.lastrowid
                                total_m_count += 1
                            
                            for idx, row in df_sheet.iterrows():
                                if idx == 0 or pd.isna(row.iloc[2]): 
                                    continue
                                
                                topico_desc = str(row.iloc[2]).strip()
                                
                                c.execute("INSERT INTO topicos (materia_id, nome) VALUES (?, ?)", (int(mat_id), topico_desc))
                                total_t_count += 1
                        
                        conn.commit()
                        st.success(f"🎉 Importação concluída! {total_m_count} novas matérias e {total_t_count} tópicos cadastrados!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao processar a planilha: {e}")

conn.close()
