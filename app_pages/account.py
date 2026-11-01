import streamlit as st
from auth_ui import auth_panel,account_panel

if st.session_state.get('personal_token'): account_panel()
else: auth_panel()
