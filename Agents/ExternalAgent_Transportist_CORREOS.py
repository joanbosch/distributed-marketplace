# -*- coding: utf-8 -*-
"""
Agente Externo Transportista CORREOS.
Envia ofertas de precios de transportes y acepta o no una petición de transporte de un pedido.

"""

from multiprocessing import Process
import socket
import argparse
import datetime

from flask import Flask, render_template, request
from rdflib import Graph, Namespace, Literal, XSD
from rdflib.namespace import FOAF, RDF
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
    port = 9018
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
app = Flask(__name__)

# Configuration constants and variables
agn = Namespace("http://www.agentes.org#")

# Contador de mensajes
mss_cnt = 0

# Datos del Agente
ExternalTransportAgent_CORREOS = Agent('ExternalTransportAgent_CORREOS',
                       agn.ExternalTransportAgent_CORREOS,
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
    reg_obj = agn[ExternalTransportAgent_CORREOS.name + '-Register']
    gmess.add((reg_obj, RDF.type, DSO.Register))
    gmess.add((reg_obj, DSO.Uri, ExternalTransportAgent_CORREOS.uri))
    gmess.add((reg_obj, FOAF.name, Literal(ExternalTransportAgent_CORREOS.name)))
    gmess.add((reg_obj, DSO.Address, Literal(ExternalTransportAgent_CORREOS.address)))
    gmess.add((reg_obj, DSO.AgentType, agn.ExternalTransportAgent))

    # Lo metemos en un envoltorio FIPA-ACL y lo enviamos
    gr = send_message(
        build_message(gmess, perf=ACL.request,
                      sender=ExternalTransportAgent_CORREOS.uri,
                      receiver=DirectoryAgent.uri,
                      content=reg_obj,
                      msgcnt=mss_cnt),
        DirectoryAgent.address)
    mss_cnt += 1

    return gr

def make_proposal(gm, content, send_to):
    peso = float(gm.value(subject=content, predicate=ECSDI.Peso))
    entrega = datetime.datetime.now() + datetime.timedelta(days=1)
    precio = peso * float(randrange(10, 30)/30)

    g = Graph()
    subject = ECSDI['Precio_Transporte'+str(mss_cnt)]
    g.add((subject, RDF.type, ECSDI.Propuesta_transporte))
    g.add((subject, ECSDI.Precio_envio, Literal(precio, datatype = XSD.float)))
    g.add((subject, ECSDI.Fecha_Entrega, Literal(entrega, datatype = XSD.dateTime)))

    g = build_message(g, ACL['propose'], sender=ExternalTransportAgent_CORREOS.uri, msgcnt=mss_cnt, receiver=send_to)
    
    logger.info("We are sending a proposal. Weight of the package: " + str(peso) + "Limit: " + str(entrega) + " and price: " + str(precio) + "." )

    return g

def make_counter_offer(old_price,  send_to, discount):

    nuevo_precio = old_price - old_price*(discount-1)
    g = Graph()
    subjectGr = ECSDI['Enviar_controferta_' + str(mss_cnt)]
    g.add((subjectGr, RDF.type, ECSDI.Enviar_contraoferta))
    g.add((subjectGr, ECSDI.Precio_envio, Literal(old_price, datatype=XSD.float)))
    g.add((subjectGr, ECSDI.Precio_contraoferta, Literal(nuevo_precio, datatype=XSD.float)))

    g = build_message(g, ACL['propose'], sender=ExternalTransportAgent_CORREOS.uri, msgcnt=mss_cnt, receiver=send_to)
    
    logger.info("We are sending a counter-proposal.")

    return g
    


@app.route("/iface", methods=['GET', 'POST'])
def browser_iface():
    """
    Permite la comunicacion con el agente via un navegador
    via un formulario
    """
    if request.method == 'GET':
        return render_template('../Templates/iface.html')
    else:
        user = request.form['username']
        mess = request.form['message']
        return render_template('../Templates/riface.html', user=user, mess=mess)


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
    Simplemente retorna un objeto fijo que representa una
    respuesta a una busqueda de hotel
    Asumimos que se reciben siempre acciones que se refieren a lo que puede hacer
    el agente (buscar con ciertas restricciones, reservar)
    Las acciones se mandan siempre con un Request
    Prodriamos resolver las busquedas usando una performativa de Query-ref
    """
    global dsgraph
    global mss_cnt

    logger.info('Peticion de informacion recibida al transportsita SEUR.')

    # Extraemos el mensaje y creamos un grafo con el
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message)

    msgdic = get_message_properties(gm)

    # Comprobamos que sea un mensaje FIPA ACL
    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=ExternalTransportAgent_CORREOS.uri, msgcnt=mss_cnt)
    else:
        # Obtenemos la performativa
        perf = msgdic['performative']

        # Al recibir una peticion para enviar un producto.
        if perf == ACL['call-for-proposal']:
            logger.info("Proposal Recived.")
            gr = make_proposal(gm, msgdic['content'], msgdic['sender'])
        
        # Si se accepta la propuesta del transportista, entonces se debe enviar el pedidio.
        elif perf == ACL['accept-proposal']:
            logger.info("La proposicón ha sido ACEPTADA por el centro logístico.")
            gr = build_message(Graph(),
                ACL['inform'],
                sender=ExternalTransportAgent_CORREOS.uri,
                msgcnt=mss_cnt,
                receiver=msgdic['sender'])

        elif perf == ACL['reject-proposal']:
            logger.info("La proposicion NO ha sido ACEPTADA por el centro logística.")
            gr = build_message(Graph(),
                ACL['inform'],
                sender=ExternalTransportAgent_CORREOS.uri,
                msgcnt=mss_cnt,
                receiver=msgdic['sender'])

        elif perf == ACL.request:

            if 'content' in msgdic:
                content = msgdic['content']
                accion = gm.value(subject=content, predicate=RDF.type)
                
                # If the external seller want to add products in our shop.
                if accion == ECSDI.Enviar_contraoferta:
                    logger.info("Se ha recibido una contra oferta.")
                    precio_inicial = 0
                    precio_oferta = 0
                    for subj in gm.subjects(RDF.type, ECSDI.Enviar_contraoferta):
                        precio_inicial = float(gm.value(subject=subj, predicate=ECSDI.Precio_envio))
                        precio_oferta = float(gm.value(subject=subj, predicate=ECSDI.Precio_contraoferta))

                    descuento = 100 - (precio_oferta/precio_inicial)*100

                    if descuento < 6:
                        logger.info("Se ACCEPTA la contra oferta.")
                        gr = build_message(Graph(),
                            ACL['accept'],
                            sender=ExternalTransportAgent_CORREOS.uri,
                            msgcnt=mss_cnt,
                            receiver=msgdic['sender'])
                    
                    elif descuento < 11:
                        logger.info("Se va a ofrecer una nueva contra oferta al centro logísitco.")
                        gr = make_counter_offer(precio_inicial, msgdic['sender'], descuento)
                    elif descuento > 10:
                        logger.info("Se RECHAZA la contra oferta proporcionada por el centro logístico.")
                        gr = build_message(Graph(),
                            ACL['reject'],
                            sender=ExternalTransportAgent_CORREOS.uri,
                            msgcnt=mss_cnt,
                            receiver=msgdic['sender'])
        elif perf == ACL['inform']:
            gr = build_message(Graph(),
                ACL['inform'],
                sender=ExternalTransportAgent_CORREOS.uri,
                msgcnt=mss_cnt,
                receiver=msgdic['sender'])

    mss_cnt += 1

    logger.info('Respondemos a la peticion')

    return gr.serialize(format='xml')



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
