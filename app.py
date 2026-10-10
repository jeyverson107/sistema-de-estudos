import streamlit as st
import pandas as pd
import datetime
import sqlite3
import time
import os

st.set_page_config(page_title="Sistema de Estudos & Carreira", layout="wide", page_icon="🛡️")

# -----------------------------------------------------------------------------
# BANCO DE DADOS DINÂMICO (CAMINHO ABSOLUTO FIXO)
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "estudos_master.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
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
