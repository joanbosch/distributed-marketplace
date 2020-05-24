# -*- coding: utf-8 -*-
"""
filename: ExternalUserAgent

Agente que busca en el directorio y llama al agente obtenido (agente SalesProcessor)
Agente que implementa la interaccion con el usuario

@author: javier
"""

from multiprocessing import Process
import socket
import argparse

from flask import Flask, render_template, request, redirect
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import FOAF, RDF, XSD
import requests

from AgentUtil.OntoNamespaces import ACL, DSO, ECSDI
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.ACLMessages import build_message, send_message
from AgentUtil.Agent import Agent
from AgentUtil.Logging import config_logger

__author__ = 'javier'

# Definimos los parametros de la linea de comandos
parser = argparse.ArgumentParser()
parser.add_argument('--open', help="Define si el servidor est abierto al exterior o no", action='store_true',
                    default=False)
parser.add_argument('--port', type=int, help="Puerto de comunicacion del agente")
parser.add_argument('--dhost', default='localhost', help="Host del agente de directorio")
parser.add_argument('--dport', type=int, help="Puerto de comunicacion del agente de directorio")

# Logging
logger = config_logger(level=1)

# parsing de los parametros de la linea de comandos
args = parser.parse_args()

# Configuration stuff
if args.port is None:
    port = 9002
else:
    port = args.port

if args.open is None:
    hostname = '0.0.0.0'
else:
    hostname = socket.gethostname()

if args.dport is None:
    dport = 9000
else:
    dport = args.dport

if args.dhost is None:
    dhostname = socket.gethostname()
else:
    dhostname = args.dhost

# Flask stuff
app = Flask(__name__, template_folder="../Templates")

# Configuration constants and variables
agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0

# Productos encontrados
products_list = []

# Productos seleccionados
products_selected = []

# Numero de productos seleccionados para comprar
numProdCarrito = 0

# Datos del Agente
ExternalUserAgent = Agent('ExternalUserAgent',
                       agn.ExternalUserAgent,
                       'http://%s:%d/comm' % (hostname, port),
                       'http://%s:%d/Stop' % (hostname, port))

# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))

# Global dsgraph triplestore
dsgraph = Graph()


def get_agent_info(type):
    """
    Busca en el servicio de registro mandando un
    mensaje de request con una accion Search del servicio de directorio
    :param type:
    :return:
    """
    global mss_cnt
    logger.info('Buscamos en el servicio de registro')

    gmess = Graph()

    gmess.bind('foaf', FOAF)
    gmess.bind('dso', DSO)
    reg_obj = agn[ExternalUserAgent.name + '-search']
    gmess.add((reg_obj, RDF.type, DSO.Search))
    gmess.add((reg_obj, DSO.AgentType, type))

    msg = build_message(gmess, perf=ACL.request,
                        sender=ExternalUserAgent.uri,
                        receiver=DirectoryAgent.uri,
                        content=reg_obj,
                        msgcnt=mss_cnt)
    gr = send_message(msg, DirectoryAgent.address)
    mss_cnt += 1
    logger.info('Recibimos informacion del agente')

    return gr


def send_message_to_agent(gmess, ragn, contentRes):
    """
    Envia una accion a un agente de informacion
    """
    global mss_cnt
    logger.info('Hacemos una peticion al servicio de informacion')

    msg = build_message(gmess, perf=ACL.request,
                        sender=ExternalUserAgent.uri,
                        receiver=ragn.uri,
                        msgcnt=mss_cnt,
                        content=contentRes)
    gr = send_message(msg, ragn.address)
    mss_cnt += 1
    logger.info('Recibimos respuesta a la peticion al servicio de informacion')

    return gr

# Interface for user. Can choose between Search product and Return Product
@app.route("/")
def browser_uhome():
    return render_template('uhome.html')

# Interface for user to search products and select them to buy them.
# 2 cases:
#   1. First time on this endpoint, shows inputs to restrict the search, method GET
#   2. User Hit the search button and shows a list of products, method POST
@app.route("/search", methods=['GET', 'POST'])
def browser_search():
    global mss_cnt
    global products_list
    global numProdCarrito
    products_list = [ 
        {
            "nombre": "iphone 11",
            "marca": "apple",
            "tipo": "tecnologia",
            "precio": 860,
            "peso": 200
        },
        {
            "nombre": "iphone 8",
            "marca": "apple",
            "tipo": "tecnologia",
            "precio": 860,
            "peso": 200
        },
        {
            "nombre": "iphoneX",
            "marca": "apple",
            "tipo": "tecnologia",
            "precio": 860,
            "peso": 200
        }
    ]
    if request.method == 'GET':
        return render_template('search.html', products=None, numCarrito=numProdCarrito)
    elif request.method == 'POST':
        # ------------------------- BUSQUEDA --------------------------------
        if request.form['submit'] == 'search':
            logger.info("Enviando peticion de busqueda.")

            # content of message
            content = ECSDI['Buscar_productos_' + str(mss_cnt)] 

            # Graph creation
            gr = Graph()
            gr.add((content, RDF.type, ECSDI.Buscar_productos))

            # Add filters
            name = request.form['name']
            if name:
                subject_nombre = ECSDI['Filtrar_nombre'+ mss_cnt]
                gr.add((subject_nombre, RDF.type, ECSDI.Filtrar_nombre))
                gr.add((subject_nombre, ECSDI.Nombre, Literal(name, datatype=XSD.string)))
                gr.add((content, ECSDI.Usa_filtro, URIRef(subject_nombre)))

            marca = request.form['brand']
            if marca:
                subject_marca = ECSDI['Filtrar_marca'+ mss_cnt]
                gr.add((subject_marca, RDF.type, ECSDI.Filtrar_marca))
                gr.add((subject_marca, ECSDI.Marca, Literal(marca, datatype=XSD.string)))
                gr.add((content, ECSDI.Usa_filtro, URIRef(subject_marca)))

            precio_min = request.form['price_min']
            precio_max = request.form['price_max']
            if precio_min or precio_max:
                subject_precio = ECSDI['Filtrar_precio'+ mss_cnt]
                gr.add((subject_precio, RDF.type, ECSDI.Filtrar_precio))
                if precio_min:
                    gr.add((subject_precio, ECSDI.Precio_minimo, Literal(precio_min, datatype=XSD.float)))
                if precio_max:
                    gr.add((subject_precio, ECSDI.Precio_maximo, Literal(precio_max, datatype=XSD.float)))
                gr.add((content, ECSDI.Usa_filtro, URIRef(subject_precio)))

            tipo = request.form['type']
            if tipo:
                subject_tipo = ECSDI['Filtrar_tipo'+ mss_cnt]
                gr.add((subject_tipo, RDF.type, ECSDI.Filtrar_tipo))
                gr.add((subject_tipo, ECSDI.Tipo, Literal(tipo, datatype=XSD.string)))
                gr.add((content, ECSDI.Usa_filtro, URIRef(subject_tipo)))
            
            vend_externo = request.form['externalSeller']
            vend_tienda = request.form['internalSeller']
            if vend_externo or vend_tienda:
                subject_vend_ext = ECSDI['Filtrar_vendedores_externos'+ mss_cnt]
                gr.add((subject_vend_ext, RDF.type, ECSDI.Filtrar_vendedores_externos))
                if vend_externo:
                    gr.add((subject_vend_ext, ECSDI.Incluir_productos_externos, Literal(vend_externo, datatype=XSD.boolean)))
                if vend_tienda:
                    gr.add((subject_vend_ext, ECSDI.Incluir_productos_tienda, Literal(vend_tienda, datatype=XSD.boolean)))
                gr.add((content, ECSDI.Usa_filtro, URIRef(subject_vend_ext)))
            

            # Buscar a l'agent Processar Compra i demanar buscar productes, assignar els productes a la products_list
            venedor = get_agent_info(agn.AgenteSimple, DirectoryAgent, ExternalUserAgent)

            ProductsGr = send_message_to_agent(gr, venedor, content)

            index = 0
            subject_pos = {}
            products_list = []
            for s, p, o in ProductsGr:
                if s not in subject_pos:
                    subject_pos[s] = index
                    products_list.append({})
                    index += 1
                if s in subject_pos:
                    subject_dict = products_list[subject_pos[s]]
                    if p == RDF.type:
                        subject_dict['url'] = s
                    elif p == ECSDI.Marca:
                        subject_dict['marca'] = o
                    elif p == ECSDI.Nombre:
                        subject_dict['nombre'] = o
                    elif p == ECSDI.Peso:
                        subject_dict['peso'] = o
                    elif p == ECSDI.Precio:
                        subject_dict['precio'] = o
                    elif p == ECSDI.Tipo:
                        subject_dict['tipo'] = o
                    products_list[subject_pos[s]] = subject_dict
            
            return render_template('search.html', products=products_list, numCarrito=numProdCarrito)

        # -------------------------- COMPRA --------------------------------

        elif request.form['submit'] == 'buy':            
            return redirect('http://%s:%d/buy' % (hostname, port))

        else:
            logger.info("Añadir producto al carrito de compra.")

            global products_selected

            index_item = request.form['submit']
            item_checked = []
            item = products_list[int(index_item)]
            item_checked.append(item['url'])
            item_checked.append(item['marca'])
            item_checked.append(item['nombre'])
            item_checked.append(item['peso'])
            item_checked.append(item['precio'])
            item_checked.append(item['tipo'])
            products_selected.append(item)

            numProdCarrito += 1
            
            return render_template('search.html', products=products_list, numCarrito=numProdCarrito)

# Interface to show the producst selected to buy to the user. 
# 2 cases:
#   1. User on search page hit Buy button, shows list of products to complete and confirm sale, method GET
#   2. User hit Confirm Buy and shows the receipt, method POST
@app.route("/buy", methods=['GET', 'POST'])
def browser_buy():
    global products_selected
    global numProdCarrito

    if request.method == 'GET':
        return render_template('buy.html', products=products_selected, saleCompleted=None)
    elif request.method == 'POST':
        if request.form['submit'] == 'buy':
            logger.info("Enviando peticion de compra.")
            
            # Content of message
            content = ECSDI['Procesar_Compra_'+mss_cnt]

            gr = Graph()
            gr.add((content, RDF.type, ECSDI.Procesar_Compra))

            priority = request.form['priority']
            gr.add((content, ECSDI.Prioridad_Entrega, Literal(priority, datatype=XSD.string)))

            address = request.form['address']
            gr.add((content, ECSDI.Direccion_Envio, Literal(address, datatype=XSD.string)))

            creditcard = request.form['creditcard']
            gr.add((content, ECSDI.Informacion_Pago, Literal(creditcard, datatype=XSD.string)))

            for prod in products_selected:
                subject_product = prod[0]
                gr.add((subject_product, RDF.type, ECSDI.Producto))
                gr.add((subject_product, ECSDI.Marca, Literal(prod[1], datatype=XSD.string)))
                gr.add((subject_product, ECSDI.Nombre, Literal(prod[2], datatype=XSD.string)))
                gr.add((subject_product, ECSDI.Peso, Literal(prod[3], datatype=XSD.integer)))
                gr.add((subject_product, ECSDI.Precio, Literal(prod[4], datatype=XSD.float)))
                gr.add((subject_product, ECSDI.Tipo, Literal(prod[5], datatype=XSD.string)))
                gr.add((content, ECSDI.Lista_Productos_ProcesarCompra, URIRef(subject_product)))

            # buscar agente Procesar Compra y enviarle mensaje
            
            venedor = get_agent_info(agn.AgenteSimple, DirectoryAgent, ExternalUserAgent)

            Respuesta = send_message_to_agent(gr, venedor, content)
            
            return render_template('buy.html', products=products_selected, saleCompleted=True)
        else:
            logger.info("Eliminando producto del carrito de compra.")

            index = request.form['submit']
            del products_selected[int(index)]
            numProdCarrito -= 1

            return render_template('buy.html', products=products_selected, saleCompleted=None)

@app.route("/return", methods=['GET', 'POST'])
def browser_return():
    global mss_cnt
    if request.method == 'GET':
        logger.info("Conseguimos y mostramos el historial de compra.")

        products_comprados = []
        # Contactar agente para conseguir el historial de compra.
        gr = Graph()

        return render_template('return.html', products=products_comprados, returnCompleted=None)

    elif request.method == 'POST':
        logger.info("Enviando peticion de devolucion.")

        products_returned = []
        
        return render_template('return.html', products=products_returned, returnCompleted=True)


@app.route("/Stop")
def stop():
    """
    Entrypoint que para el agente
    :return:
    """
    tidyup()
    shutdown_server()
    return "Parando Servidor"


@app.route("/comm")
def comunicacion():
    """
    Entrypoint de comunicacion del agente
    """
    return "Hola"


def tidyup():
    """
    Acciones previas a parar el agente
    """
    pass


def agentbehavior1():
    """
    Un comportamiento del agente
    :return:
    
    # Selfdestruct
    requests.get(ExternalUserAgent.stop)
    """

if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1)
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()
    logger.info('The End')