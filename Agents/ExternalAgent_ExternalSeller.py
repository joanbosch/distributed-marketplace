# -*- coding: utf-8 -*-
"""
Agente Externo de Vendedor Externo. 
Agente implementa la interacción con un vendedor externo.

"""

from multiprocessing import Process
import socket
import argparse
import datetime
import random
import sys

from flask import Flask, render_template, request
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import FOAF, RDF, XSD
import requests

from AgentUtil.OntoNamespaces import ACL, DSO, ECSDI
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.ACLMessages import build_message, send_message, get_message_properties
from AgentUtil.Agent import Agent
from AgentUtil.Logging import config_logger

# For random numbers
from random import randrange

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
    port = 9008
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

# Name Shop and Pay
nameShop = ""
pago = "" 

# Datos del Agente
ExternalAgentOfExternalSeller = Agent('ExternalAgentOfExternalSeller',
                       agn.ExternalAgentOfExternalSeller,
                       'http://%s:%d/comm' % (hostname, port),
                       'http://%s:%d/Stop' % (hostname, port))

# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))

# Global dsgraph triplestore
dsgraph = Graph()


def register_message():
    """
    Envia un mensaje de registro al servicio de registro
    usando una performativa Request y una accion Register del
    servicio de directorio
    :param gmess:
    :return:
    """

    logger.info('Nos registramos')

    global mss_cnt

    gmess = Graph()

    # Construimos el mensaje de registro
    gmess.bind('foaf', FOAF)
    gmess.bind('dso', DSO)
    reg_obj = agn[ExternalAgentOfExternalSeller.name + '-Register']
    gmess.add((reg_obj, RDF.type, DSO.Register))
    gmess.add((reg_obj, DSO.Uri, ExternalAgentOfExternalSeller.uri))
    gmess.add((reg_obj, FOAF.name, Literal(ExternalAgentOfExternalSeller.name)))
    gmess.add((reg_obj, DSO.Address, Literal(ExternalAgentOfExternalSeller.address)))
    gmess.add((reg_obj, DSO.AgentType, ECSDI.Vendedor_externo))

    # Lo metemos en un envoltorio FIPA-ACL y lo enviamos
    gr = send_message(
        build_message(gmess, perf=ACL.request,
                      sender=ExternalAgentOfExternalSeller.uri,
                      receiver=DirectoryAgent.uri,
                      content=reg_obj,
                      msgcnt=mss_cnt),
        DirectoryAgent.address)
    mss_cnt += 1

    return gr

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
    reg_obj = agn[ExternalAgentOfExternalSeller.name + '-search']
    gmess.add((reg_obj, RDF.type, DSO.Search))
    gmess.add((reg_obj, DSO.AgentType, type))

    msg = build_message(gmess, perf=ACL.request,
                        sender=ExternalAgentOfExternalSeller.uri,
                        receiver=DirectoryAgent.uri,
                        content=reg_obj,
                        msgcnt=mss_cnt)
    gr = send_message(msg, DirectoryAgent.address)
    mss_cnt += 1
    logger.info('Recibimos informacion del agente')

    dic = get_message_properties(gr)
    content = dic['content']
    address = gr.value(subject=content, predicate=DSO.Address)
    url = gr.value(subject=content, predicate=DSO.Uri)
    name = gr.value(subject=content, predicate=FOAF.name)

    return Agent(name, url, address, None)

def send_message_to_agent(gmess, ragn, contentRes):
    """
    Envia una accion a un agente de informacion
    """
    global mss_cnt
    logger.info('Hacemos una peticion al servicio de informacion')

    msg = build_message(gmess, perf=ACL.request,
                        sender=ExternalAgentOfExternalSeller.uri,
                        receiver=ragn.uri,
                        msgcnt=mss_cnt,
                        content=contentRes)
    gr = send_message(msg, ragn.address)
    mss_cnt += 1
    logger.info('Recibimos respuesta a la peticion al servicio de informacion')

    return gr

#Interface for shop.
@app.route("/")
def browser_externalseller():
    return render_template('externalseller.html')


@app.route("/register_product", methods=['GET', 'POST'])
def browser_register_product():

    global mss_cnt
    global nameShop
    global pago

    if request.method == 'GET':

        return render_template('register_product.html', response=None)
        
    elif request.method == 'POST':

        if request.form['submit'] == 'deal':

            logger.info("Enviamos peticion de acuerdo de la tienda")

            # Valores del formulario del Vendedor a registrar
            pago = request.form['pago']
            nameShop = request.form['name']
            
            gr = Graph()

            # Accion Registrar Vendedor Externo
            content = ECSDI['Pedir_Acuerdo_Tienda_' + str(mss_cnt)] 
            gr.add((content, RDF.type, ECSDI.Pedir_Acuerdo_Tienda))
            
            # Vendedor Externo a registrar
            subject = ECSDI['Vendedor_externo'+ str(mss_cnt)]
            gr.add((subject, RDF.type, ECSDI.Vendedor_externo))
            gr.add((subject, ECSDI.Nombre, Literal(nameShop, datatype=XSD.string)))
            gr.add((subject, ECSDI.Forma_pago, Literal(pago, datatype=XSD.string)))

            gr.add((content, ECSDI.Vendedor_A_Registrar, URIRef(subject)))

            # Obtenemos el Agente (interno) Vendedor Externo
            seller = get_agent_info(agn.ExternalSellerAgent)

            # Enviamos el Vendedor Externo para que sea registrado
            deal_responseGr = send_message_to_agent(gr, seller, content)

             # Obtenemos la respuesta
            subjectGraph = deal_responseGr.subjects(RDF.type, ECSDI.Responder_Acuerdo_Tienda)
            for s in subjectGraph:
                respuesta = str(deal_responseGr.value(subject=s, predicate=ECSDI.Resolucion_Acuerdo))

            return render_template('register_product.html', response=respuesta)

        elif request.form['submit'] == 'registrar':

            logger.info("Enviamos registrar producto externo")

            # Valores del formulario del producto a registrar
            brand = request.form['brand']
            name = request.form['name']
            price = request.form['price']
            weight = request.form['weigth']
            tipo = request.form['tipo']

            gr = Graph()

            # Accion Registrar Producto Externo
            content = ECSDI['Registrar_Producto_Externo_' + str(mss_cnt)]
            gr.add((content, RDF.type, ECSDI.Registrar_Producto_Externo))

            # New external product
            subjectProd = ECSDI['Producto_externo_' + str(mss_cnt)]
            gr.add((subjectProd, RDF.type, ECSDI.Producto_externo))
            gr.add((subjectProd, ECSDI.Nombre, Literal(name, datatype=XSD.string)))
            gr.add((subjectProd, ECSDI.Marca, Literal(brand, datatype=XSD.string)))
            gr.add((subjectProd, ECSDI.Precio, Literal(price, datatype=XSD.float)))
            gr.add((subjectProd, ECSDI.Peso, Literal(weight, datatype=XSD.integer)))
            gr.add((subjectProd, ECSDI.Tipo, Literal(tipo, datatype=XSD.float)))

            gr.add((content, ECSDI.Producto_a_Registrar, URIRef(subjectProd)))

            # Vendedor Externo
            subjectVendedor = ECSDI['Vendedor_externo_' + str(mss_cnt)]
            gr.add((subjectVendedor, RDF.type, ECSDI.Vendedor_externo))
            gr.add((subjectVendedor, ECSDI.Nombre, Literal(nameShop, datatype=XSD.string)))
            gr.add((subjectVendedor, ECSDI.Forma_pago, Literal(pago, datatype=XSD.string)))

            gr.add((subjectProd, ECSDI.Vendido_por, URIRef(subjectVendedor)))

            # Obtenemos el Agente (interno) Vendedor Externo
            seller = get_agent_info(agn.ExternalSellerAgent)

            # Enviamos el producto para que sea registrado
            messageGr = send_message_to_agent(gr, seller, content)

             # Obtenemos la respuesta
            subjectGraph = messageGr.subjects(RDF.type, ECSDI.Producto_Registrado)
            for s in subjectGraph:
                
                respuesta = str(messageGr.value(subject=s, predicate=ECSDI.Estado_registro))

            res = {'marca': brand, 'nom': name, 'model': tipo, 'preu':price, 'peso': weight}

            return render_template('end_register_product.html', message=respuesta, product=res)

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
    """

    # Registramos el agente
    gr = register_message()


if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1)
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()
    logger.info('The End')
