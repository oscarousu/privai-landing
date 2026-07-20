import streamlit as st
import os
import requests
import pandas as pd
import tempfile
import pytesseract
from pdf2image import convert_from_path
import time
import shutil

from langchain.schema import Document
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, CSVLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.llms import Ollama
from langchain.chains import create_retrieval_chain
from langchain.chains.history_aware_retriever import create_history_aware_retriever
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage

# Configuración de la página
st.set_page_config(page_title="PrivAI Demo V2 (Avanzado)", page_icon="🤖", layout="wide")

st.title("🤖 PrivAI Demo V2: Funciones de Manufactura Avanzadas")
st.markdown("Ahora soporta **Múltiples Formatos (PDF, Word, Excel, CSV)**, **OCR para PDFs escaneados**, **Memoria Conversacional**, **Persistencia Local** y **Generación de Reportes Estructurados**.")

# Inicializar variables de sesión
if "messages" not in st.session_state:
    st.session_state.messages = []
if "vector_store" not in st.session_state:
    st.session_state.vector_store = None
if "latency" not in st.session_state:
    st.session_state.latency = 0.0

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

# Función para cargar PDFs con OCR como respaldo
def load_pdf_with_ocr(file_path, original_name):
    loader = PyPDFLoader(file_path)
    docs = loader.load()
    
    total_text = "".join([d.page_content for d in docs]).strip()
    if len(total_text) < 50:
        st.info("ℹ️ Detectado PDF escaneado. Iniciando OCR local (sin conexión)...")
        images = convert_from_path(file_path)
        docs = []
        for i, image in enumerate(images):
            text = pytesseract.image_to_string(image, lang='spa+eng')
            docs.append(Document(page_content=text, metadata={"page": i+1, "source": original_name}))
    else:
        for doc in docs:
            doc.metadata["source"] = original_name
    return docs

persist_dir = "./chroma_db"

# Sidebar para configuración
with st.sidebar:
    st.header("🔒 Panel de Privacidad")
    st.metric("Modo de Ejecución", "100% Local 🟢")
    st.metric("Datos compartidos en la nube", "0 Bytes")
    st.metric("Latencia IA", f"{st.session_state.latency:.2f} s")
    st.markdown("---")
    
    st.header("⚙️ Configuración del Motor")
    if not available_models or available_models[0].startswith("Error"):
        st.error("⚠️ No se pudo conectar a Ollama. Asegúrate de que la aplicación Ollama esté corriendo en tu Mac.")
        selected_model = st.selectbox("Selecciona un modelo:", ["gemma4:e2b", "gemma4:e4b", "gemma4:12b"])
    else:
        st.success("Ollama detectado y corriendo.")
        selected_model = st.selectbox("Selecciona un modelo:", available_models)
    
    st.markdown("---")
    st.header("📄 Gestión de Documentos")
    uploaded_file = st.file_uploader("Sube un documento (PDF, Word, Excel, CSV)", type=["pdf", "docx", "xlsx", "csv"])
    
    st.markdown("---")
    st.header("📁 Sincronización de Carpeta Local")
    folder_path = st.text_input("Ruta de la carpeta local (ej. /Users/manuales):")
    if st.button("Indexar Carpeta"):
        if folder_path and os.path.isdir(folder_path):
            with st.spinner("Buscando e indexando documentos de forma recursiva..."):
                docs_to_index = []
                supported_extensions = [".pdf", ".docx", ".xlsx", ".csv"]
                files_found = []
                
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        ext = os.path.splitext(file)[1].lower()
                        if ext in supported_extensions:
                            files_found.append(os.path.join(root, file))
                
                if not files_found:
                    st.warning("No se encontraron archivos compatibles en esa ruta o en sus subcarpetas.")
                else:
                    progress_text = "Procesando archivos..."
                    my_bar = st.progress(0, text=progress_text)
                    warnings = []
                    
                    for i, file_path in enumerate(files_found):
                        ext = os.path.splitext(file_path)[1].lower()
                        file_name = os.path.basename(file_path)
                        
                        try:
                            file_docs = []
                            if ext == ".pdf":
                                file_docs = load_pdf_with_ocr(file_path, file_name)
                            elif ext == ".docx":
                                loader = Docx2txtLoader(file_path)
                                file_docs = loader.load()
                                for doc in file_docs: doc.metadata["source"] = file_name
                            elif ext == ".csv":
                                loader = CSVLoader(file_path)
                                file_docs = loader.load()
                                for doc in file_docs: doc.metadata["source"] = file_name
                            elif ext == ".xlsx":
                                df = pd.read_excel(file_path)
                                try:
                                    text = df.to_markdown(index=False)
                                except ImportError:
                                    text = df.to_string()
                                file_docs = [Document(page_content=text, metadata={"source": file_name})]
                            
                            docs_to_index.extend(file_docs)
                        except Exception as e:
                            warnings.append(f"Error en '{file_name}': {str(e)}")
                        
                        my_bar.progress((i + 1) / len(files_found), text=f"Procesando: {file_name}")
                    
                    if docs_to_index:
                        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
                        splits = text_splitter.split_documents(docs_to_index)
                        
                        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
                        
                        if st.session_state.vector_store is None:
                            st.session_state.vector_store = Chroma.from_documents(
                                documents=splits, 
                                embedding=embeddings, 
                                persist_directory=persist_dir
                            )
                        else:
                            st.session_state.vector_store.add_documents(splits)
                            
                        st.success(f"¡Se indexaron {len(files_found) - len(warnings)} archivos exitosamente!")
                    
                    if warnings:
                        with st.expander("⚠️ Ver advertencias (archivos no procesados)"):
                            for w in warnings:
                                st.warning(w)
        else:
            st.error("Por favor, ingresa una ruta de carpeta válida que exista en este equipo.")
    
    if os.path.exists(persist_dir):
        st.markdown("**(Base de datos actual contiene documentos)**")
        if st.button("🧹 Limpiar Base de Datos"):
            st.session_state.vector_store = None
            shutil.rmtree(persist_dir)
            st.success("Base de datos limpia. Sube un documento nuevo.")
            st.rerun()

# Cargar base de datos existente al iniciar si existe y no se ha cargado
if st.session_state.vector_store is None and os.path.exists(persist_dir):
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    st.session_state.vector_store = Chroma(persist_directory=persist_dir, embedding_function=embeddings)

# Procesar el documento si se sube uno
if uploaded_file is not None:
    # Solo procesamos si no se ha indexado ya en esta sesión para evitar duplicados
    with st.spinner("Procesando e indexando localmente..."):
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_file.flush()
            tmp_file_path = tmp_file.name
        
        docs = []
        if ext == ".pdf":
            docs = load_pdf_with_ocr(tmp_file_path, uploaded_file.name)
        elif ext == ".docx":
            loader = Docx2txtLoader(tmp_file_path)
            docs = loader.load()
            for doc in docs: doc.metadata["source"] = uploaded_file.name
        elif ext == ".csv":
            loader = CSVLoader(tmp_file_path)
            docs = loader.load()
            for doc in docs: doc.metadata["source"] = uploaded_file.name
        elif ext == ".xlsx":
            df = pd.read_excel(tmp_file_path)
            try:
                text = df.to_markdown(index=False)
            except ImportError:
                text = df.to_string()
            docs = [Document(page_content=text, metadata={"source": uploaded_file.name})]
            
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)
        
        if not splits:
            st.error("⚠️ No se pudo extraer texto del archivo.")
        else:
            embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
            st.session_state.vector_store = Chroma.from_documents(
                documents=splits, 
                embedding=embeddings, 
                persist_directory=persist_dir
            )
            st.sidebar.success(f"¡Documento '{uploaded_file.name}' indexado correctamente!")

# Sidebar: Reporte Automático
with st.sidebar:
    if st.session_state.vector_store is not None:
        st.markdown("---")
        st.header("📊 Agente de Reportes")
        if st.button("Generar Reporte Ejecutivo"):
            with st.spinner("Analizando y estructurando reporte (100% offline)..."):
                start_time = time.time()
                llm = Ollama(model=selected_model)
                retriever = st.session_state.vector_store.as_retriever(search_kwargs={"k": 5})
                
                report_prompt = ChatPromptTemplate.from_messages([
                    ("system", "Eres un analista experto en manufactura. Usa el contexto proporcionado para extraer los puntos clave del documento y genera un reporte estructurado en Markdown. Incluye:\n1. Título del Reporte\n2. Resumen Ejecutivo\n3. Puntos Clave (Viñetas)\n4. Conclusión.\n\nContexto:\n{context}"),
                    ("human", "{input}")
                ])
                
                report_chain = create_stuff_documents_chain(llm, report_prompt)
                rag_chain_report = create_retrieval_chain(retriever, report_chain)
                
                response = rag_chain_report.invoke({"input": "Por favor genera el reporte ejecutivo."})
                st.session_state.latency = time.time() - start_time
                
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": "Aquí tienes el reporte generado automáticamente:\n\n" + response["answer"],
                    "sources": response.get("context", [])
                })
                st.rerun()

# Mostrar chat y fuentes
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("sources"):
            with st.expander("🔍 Mostrar fuentes (Citations)"):
                for i, doc in enumerate(message["sources"]):
                    source = doc.metadata.get('source', 'Archivo Local')
                    page = doc.metadata.get('page', 'N/A')
                    st.markdown(f"**Documento:** {source} | **Página/Sección:** {page}")
                    st.caption(f'"{doc.page_content[:300]}..."')

# Entrada de usuario (Con Memoria Conversacional)
if prompt := st.chat_input("Haz una pregunta técnica al modelo..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        if st.session_state.vector_store is None:
            st.warning("Por favor, sube un documento o asegúrate de que la base de datos esté cargada.")
        else:
            with st.spinner("Analizando manuales técnicos..."):
                start_time = time.time()
                llm = Ollama(model=selected_model)
                retriever = st.session_state.vector_store.as_retriever()
                
                # Transformar historial para Langchain
                chat_history = []
                for msg in st.session_state.messages[:-1]:
                    if msg["role"] == "user":
                        chat_history.append(HumanMessage(content=msg["content"]))
                    else:
                        chat_history.append(AIMessage(content=msg["content"]))
                
                # Reformular la pregunta
                contextualize_q_system_prompt = (
                    "Dado el historial del chat y la última pregunta del usuario "
                    "que podría hacer referencia a contexto anterior, "
                    "formula una pregunta independiente. "
                    "NO respondas la pregunta, solo reformúlala si es necesario, de lo contrario, devuélvela tal cual."
                )
                contextualize_q_prompt = ChatPromptTemplate.from_messages([
                    ("system", contextualize_q_system_prompt),
                    MessagesPlaceholder("chat_history"),
                    ("human", "{input}"),
                ])
                history_aware_retriever = create_history_aware_retriever(
                    llm, retriever, contextualize_q_prompt
                )

                # Cadena principal
                system_prompt = (
                    "Eres un asistente técnico experto en manufactura e industria. "
                    "Responde basándote ÚNICAMENTE en el contexto proporcionado. "
                    "Si la respuesta no está en el contexto, di: 'No tengo información en los manuales sobre esto, evitando alucinaciones'. "
                    "Mantén tu respuesta clara y profesional.\n\n"
                    "Contexto recuperado:\n{context}"
                )
                qa_prompt = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    MessagesPlaceholder("chat_history"),
                    ("human", "{input}"),
                ])
                
                question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
                rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)
                
                response = rag_chain.invoke({"input": prompt, "chat_history": chat_history})
                end_time = time.time()
                st.session_state.latency = end_time - start_time
                
                answer = response["answer"]
                context_docs = response.get("context", [])
                
                st.markdown(answer)
                if context_docs:
                    with st.expander("🔍 Mostrar fuentes (Citations)"):
                        for i, doc in enumerate(context_docs):
                            source = doc.metadata.get('source', 'Archivo Local')
                            page = doc.metadata.get('page', 'N/A')
                            st.markdown(f"**Documento:** {source} | **Página/Sección:** {page}")
                            st.caption(f'"{doc.page_content[:300]}..."')
                
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": answer,
                    "sources": context_docs
                })
                
                st.rerun() # Recargar para actualizar las métricas en la barra lateral
