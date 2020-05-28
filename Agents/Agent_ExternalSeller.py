"""
Created on Fri Dec 27 15:58:13 2013
Esqueleto de agente usando los servicios web de Flask
/comm es la entrada para la recepcion de mensajes del agente
/Stop es la entrada que para el agente
Tiene una funcion AgentBehavior1 que se lanza como un thread concurrente
Asume que el agente de registro esta en el puerto 9000
@author: javier
"""

from multiprocessing import Process, Queue
import argparse
import socket
import requests
import random
import sys

from flask import Flask, request
from rdflib import Namespace, Graph, Literal, XSD
from rdflib.namespace import FOAF, RDF, RDFS

from AgentUtil.ACLMessages import build_message, send_message, get_message_properties
from AgentUtil.Agent import Agent
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.Logging import config_logger
from AgentUtil.OntoNamespaces import ACL, DSO, ECSDI

__author__ = 'javier'


# Definimos los parametros de la linea de comandos
parser = argparse.ArgumentParser()
parser.add_argument('--open', help="Define si el servidor esta abierto al exterior o no", action='store_true',
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
    port = 9007
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

# Configuration constants and variables
agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0

# Information about this agent (must be reviewed)
ExternalSellerAgent = Agent('ExternalSellerAgent',
                       agn.ExternalSellerAgent,
                       'http://%s:%d/comm' % (hostname, port),
                       'http://%s:%d/Stop' % (hostname, port))

# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:9000/Register' % hostname,
                       'http://%s:9000/Stop' % hostname)


# Global triplestore graph
dsgraph = Graph()

cola1 = Queue()

# Flask stuff
app = Flask(__name__)

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
    reg_obj = agn[ExternalSellerAgent.name + '-Register']
    gmess.add((reg_obj, RDF.type, DSO.Register))
    gmess.add((reg_obj, DSO.Uri, ExternalSellerAgent.uri))
    gmess.add((reg_obj, FOAF.name, Literal(ExternalSellerAgent.name)))
    gmess.add((reg_obj, DSO.Address, Literal(ExternalSellerAgent.address)))
    gmess.add((reg_obj, DSO.AgentType, agn.ExternalSellerAgent)) 

    # Lo metemos en un envoltorio FIPA-ACL y lo enviamos
    gr = send_message(
        build_message(gmess, perf=ACL.request,
                      sender=ExternalSellerAgent.uri,
                      receiver=DirectoryAgent.uri,
                      content=reg_obj,
                      msgcnt=mss_cnt),
        DirectoryAgent.address)
    mss_cnt += 1

    return gr

def get_external_sellers():
    logger.info("Obteniendo todos los vendedores externos.")
     
    g = Graph()
    g.parse(open('../Data/external_sellers'), format='turtle')

    sellers = []

    for seller in g.subjects(RDF.type, ECSDI.Vendedor_externo):
        sell = {}
        sell['url'] = seller
        sell['Nombre'] = (str(g.value(subject=seller, predicate=ECSDI.Nombre)))
        sellers.append(sell)
    
    return sellers

def is_external_seller(name):
    logger.info("Comprobando si el vendedor esta registrado.")
     
    g = Graph()
    g.parse(open('../Data/external_sellers'), format='turtle')

    sellers = []

    for seller in g.subjects(RDF.type, ECSDI.Vendedor_externo):
        nombre = (str(g.value(subject=seller, predicate=ECSDI.Nombre)))
        if name == nombre:
            return True
    
    return False

def register_external_seller(gm, content):
    logger.info("Registrando al vendedor externo.")
    new_seller = Graph()
    new_seller.parse(open('../Data/external_sellers'), format='turtle')

    #Obtain the external seller values
    name = gm.value(subject=content, predicate=ECSDI.Nombre_Tienda)

    # External Seller Random number to asign 
    subjectSeller = ECSDI['Vendedor_externo_'+ str(random.randint(1, sys.float_info.max))]

    new_seller.add((subjectSeller, RDF.type, ECSDI.Vendedor_Externo))
    new_seller.add((subjectSeller, ECSDI.Nombre,Literal(name, datatype=XDS.string)))

    new_seller.serialize(destination='../Data/external_sellers', format='turtle')

    
@app.route("/comm")
def comunicacion():
    """
    Entrypoint de comunicacion
    """
    global dsgraph
    global mss_cnt

    logger.info('Peticion de informacion recibida')

    # Extraemos el mensaje y creamos un grafo con el
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message)

    msgdic = get_message_properties(gm)

    # Comprobamos que sea un mensaje FIPA ACL
    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=ExternalSellerAgent.uri, msgcnt=mss_cnt)
    else:
        # Obtenemos la performativa
        perf = msgdic['performative']

        if perf != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(), ACL['not-understood'], sender=ExternalSellerAgent.uri, msgcnt=mss_cnt)
        else:
            # Extraemos el objeto del contenido que ha de ser una accion de la ontologia de acciones del agente
            # de registro

            # Averiguamos el tipo de la accion
            if 'content' in msgdic:
                content = msgdic['content']
                accion = gm.value(subject=content, predicate=RDF.type)
                
                # If the external seller want to add products in our shop.
                if accion == ECSDI.Pedir_Acuerdo_Tienda:
                    logger.info('Se ha pedido un acuerdo entre un vendedor externo y la tienda.')
                    # WE must check:
                    # 1. If the seller has already been granted, return a message informing that the user has already permissions to add products.
                    # 2. If the seller is not in our BD, register it and repond them that forn now he can add external products to our shop, and register it in our DB.
                    # 3. ¿Decline the access to our shop? 
                    
                    # Response with the action ECSDI.Resolucion_Acuerdo, preformative: accept-proposal/reject-proposal

                    nombre = gm.objects(content, ECSDI.Nombre_Tienda)
                    if is_external_seller(nombre):

                        gr = build_message(Graph(),
                        ACL['agree'],
                        sender=ExternalSellerAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'])

                    else:
                        register_external_seller(gm, content)

                        gr = build_message(Graph(),
                        ACL['accept-proposal'],
                        sender=ExternalSellerAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'])

                # Register external products to the shop
                elif accion == ECSDI.Registrar_Producto_Externo:
                    logger.info('Se va a registrar un producto externo')
                    # We must to the next:
                    # 1. Check that the external seller can add products. If not, respond with a message with  the preformative Refuse
                    # 2. If the seller can add products, send a message to Agent_SalesProcessor to register the new product
                    
                    nombre = gm.objects(content, ECSDI.Nombre_Tienda)
                    if is_external_seller(nombre):
                        gr = build_message(Graph(),
                        ACL['agree'],
                        sender=ExternalSellerAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'])

                    else:
                        gr = build_message(Graph(),
                        ACL['refuse'],
                        sender=ExternalSellerAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'])


                elif accion == ECSDI.Producto_Registrado:
                    # We only have to reponse to the External Seller with the response of the Sales Processor.

                else:
                    gr = build_message(Graph(),
                        ACL['not-understood'],
                        sender=ExternalSellerAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'])

            # Aqui realizariamos lo que pide la accion
            # Por ahora simplemente retornamos un Inform-done
            #gr = build_message(Graph(),
            #    ACL['inform-done'],
            #    sender=SalesProcessorAgent.uri,
            #    msgcnt=mss_cnt,
            #    receiver=msgdic['sender'], )
    mss_cnt += 1

    logger.info('Respondemos a la peticion')

    return gr.serialize(format='xml')


@app.route("/Stop")
def stop():
    """
    Entrypoint que para el agente
    :return:
    """
    tidyup()
    shutdown_server()
    return "Parando Servidor"


def tidyup():
    """
    Acciones previas a parar el agente
    """
    global cola1
    cola1.put(0)


def agentbehavior1(cola):
    """
    Un comportamiento del agente
    :return:
    """
    #Registramos el agente
    gr = register_message()

def get_agent_info(type_, directory_agent, sender, msgcnt):
    gmess = Graph()
    # Construimos el mensaje de registro
    gmess.bind('foaf', FOAF)
    gmess.bind('dso', DSO)
    ask_obj = agn[sender.name + '-Search']

    gmess.add((ask_obj, RDF.type, DSO.Search))
    gmess.add((ask_obj, DSO.AgentType, type_))
    gr = send_message(
        build_message(gmess, perf=ACL.request, sender=sender.uri, receiver=directory_agent.uri, msgcnt=msgcnt,
                      content=ask_obj),
        directory_agent.address
    )
    dic = get_message_properties(gr)
    content = dic['content']

    address = gr.value(subject=content, predicate=DSO.Address)
    url = gr.value(subject=content, predicate=DSO.Uri)
    name = gr.value(subject=content, predicate=FOAF.name)

    return Agent(name, url, address, None)


if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()
    print('The End')