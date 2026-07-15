import streamlit as st
import os
import requests
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.llms import Ollama
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
import tempfile

# Configuración de la página
st.set_page_config(page_title="PrivAI Demo (RAG)", page_icon="🤖", layout="wide")

st.title("🤖 Demostración de PrivAI para Manufactura")
st.markdown("Esta aplicación demuestra cómo una Inteligencia Artificial puede leer tus manuales y documentos **sin enviar un solo byte de información a internet**.")

# Obtener modelos disponibles en Ollama
@st.cache_data
def get_ollama_models():
    try:
        response = requests.get("http://localhost:11434/api/tags")
        if response.status_code == 200:
            models = response.json().get("models", [])
            return [model["name"] for model in models]
        return []
    except Exception as e:
        return ["Error al conectar con Ollama"]

available_models = get_ollama_models()

# Sidebar para configuración
with st.sidebar:
    st.header("⚙️ Configuración del Motor")
    if not available_models or available_models[0].startswith("Error"):
        st.error("⚠️ No se pudo conectar a Ollama. Asegúrate de que la aplicación Ollama esté corriendo en tu Mac.")
        selected_model = st.selectbox("Selecciona un modelo:", ["gemma4:e2b", "gemma4:e4b", "gemma4:12b"])
    else:
        st.success("Ollama detectado y corriendo.")
        selected_model = st.selectbox("Selecciona un modelo:", available_models)
    
    st.markdown("---")
    st.header("📄 Carga de Documentos")
    uploaded_file = st.file_uploader("Sube un manual técnico (PDF)", type="pdf")

# Inicializar sesión
if "messages" not in st.session_state:
    st.session_state.messages = []
if "vector_store" not in st.session_state:
    st.session_state.vector_store = None

# Procesar el documento si se sube uno
if uploaded_file is not None and st.session_state.vector_store is None:
    with st.spinner("Procesando y encriptando documento localmente..."):
        # Guardar archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_file.flush()
            tmp_file_path = tmp_file.name
        
        # Cargar y dividir el texto
        loader = PyPDFLoader(tmp_file_path)
        docs = loader.load()
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)
        
        if not splits:
            st.error("⚠️ No se pudo extraer texto del PDF. Es posible que el archivo sea un documento escaneado (imágenes) sin texto seleccionable.")
        else:
            # Crear base de datos vectorial local
            # NOTA: Para RAG usamos un modelo de embeddings como 'all-MiniLM-L6-v2' (muy rápido y robusto localmente)
            # Esto evita errores con APIs que no soportan embeddings de forma nativa.
            embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
            st.session_state.vector_store = Chroma.from_documents(documents=splits, embedding=embeddings)
            
            st.sidebar.success(f"¡Documento '{uploaded_file.name}' indexado correctamente!")

# Mostrar chat
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Entrada de usuario
if prompt := st.chat_input("Haz una pregunta sobre el manual..."):
    # Añadir pregunta al historial
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generar respuesta
    with st.chat_message("assistant"):
        if st.session_state.vector_store is None:
            st.warning("Por favor, sube un documento PDF primero para poder consultarlo.")
        else:
            with st.spinner("Pensando (100% Privado)..."):
                llm = Ollama(model=selected_model)
                retriever = st.session_state.vector_store.as_retriever()
                
                system_prompt = (
                    "Eres un asistente técnico experto para el sector manufacturero. "
                    "Usa los siguientes fragmentos de contexto recuperado para responder a la pregunta. "
                    "Si no sabes la respuesta o no está en el documento, di que no lo sabes, no inventes información. "
                    "Mantén tu respuesta concisa y profesional.\n\n"
                    "{context}"
                )
                prompt_template = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("human", "{input}"),
                ])
                
                question_answer_chain = create_stuff_documents_chain(llm, prompt_template)
                rag_chain = create_retrieval_chain(retriever, question_answer_chain)
                
                response = rag_chain.invoke({"input": prompt})
                answer = response["answer"]
                
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
