# -*- coding: utf-8 -*-
"""
Agente Centro Logístico. 
Gestiona los lotes y gestiona el transporte de un pedido.

"""

from multiprocessing import Process, Queue
import socket
import argparse
from datetime import datetime, timedelta

from flask import Flask, render_template, request
from rdflib import Graph, Namespace, Literal, XSD, URIRef
from rdflib.namespace import FOAF, RDF
import requests
import random
import sys

from AgentUtil.OntoNamespaces import ACL, DSO, ECSDI
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.ACLMessages import build_message, send_message, get_message_properties
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
    port = 9003
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

# Datos del Agente Centro Logistico
LogisticCenterAgent = Agent('LogisticCenterAgent',
                       agn.LogisticCenterAgent,
                       'http://%s:%d/comm' % (hostname, port),
                       'http://%s:%d/Stop' % (hostname, port))

# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))

# Global dsgraph triplestore
dsgraph = Graph()

#Queue of processes communication
queue = Queue()

def register_message():

    """
        Envia un mensaje de registro al servicio de registro
        usando una performativa Request y una accion Register del
        servicio de directorio
        :param gmess:
        :return:
    """

    logger.info('Registramos el Agente Centro Logistico')

    global mss_cnt

    gmess = Graph()
    # Construimos el mensaje de registro
    gmess.bind('foaf', FOAF)
    gmess.bind('dso', DSO)
    reg_obj = agn[LogisticCenterAgent.name + '-Register']
    gmess.add((reg_obj, RDF.type, DSO.Register))
    gmess.add((reg_obj, DSO.Uri, LogisticCenterAgent.uri))
    gmess.add((reg_obj, FOAF.name, Literal(LogisticCenterAgent.name)))
    gmess.add((reg_obj, DSO.Address, Literal(LogisticCenterAgent.address)))
    gmess.add((reg_obj, DSO.AgentType, agn.LogisticCenterAgent))

    # Lo metemos en un envoltorio FIPA-ACL y lo enviamos
    gr = send_message(
        build_message(gmess, 
                      perf=ACL.request,
                      sender=LogisticCenterAgent.uri,
                      receiver=DirectoryAgent.uri,
                      content=reg_obj,
                      msgcnt=mss_cnt),
        DirectoryAgent.address)
    mss_cnt += 1

    return gr


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
        Busqueda de un Centro Logitico disponible
    """
    global dsgraph 
    global mss_cnt

    logger.info('Peticion de informacion recibida')

    #Extraemos el mensaje y creamos un grafo con el
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message)

    msgdic = get_message_properties(gm)

    #Comprobamos que el mensaje sera FIPA ACL
    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=LogisticCenterAgent.uri, msgcnt=mss_cnt)
    else:
        
        perf = msgdic['performative']

        if perf == ACL['request']:

            # Contenido del pedido: ciudad destino + prioridad entrega + peso total pedido
            logger.info('Peticion de envío de pedido.')

            # Añadimos el pedido al registro de lotes a enviar
            add_to_lote(gm, msgdic['content'])

            # Comprobamos si podemos enviar lotes
            if time_to_send():

                logger.info('Se envian lotes a los transportistas')

                # Enviamos
                createSend()
            gr =build_message(Graph(), 
                    perf = ACL['inform-done'], 
                    sender = LogisticCenterAgent.uri, 
                    receiver = msgdic['sender'],
                    msgcnt = mss_cnt)
    mss_cnt += 1

    logger.info('Respondemos a la peticion')
    
    return gr.serialize(format='xml')

def tidyup():
    """
    Acciones previas a parar el agente

    """
    global queue
    queue.put(0)

    pass


def agentbehavior1(queue):
    """
    Un comportamiento del agente
    :param queue: the queue
    :return:
    """

    # Registramos el Agente Centro Logistico
    gr = register_message()

    # Escuchando la cola hasta que llegue un 0
    """
    fin = False
    pass
    while not fin:
        while queue.empty():
            pass
        v = queue.get()
        if v == 0:
            fin = True
        else:
            print(v)

            # Selfdestruct
            # requests.get(LogisticCenterAgent.stop)
    """

def time_to_send():

    #Enviamos paquetes de 9:00 a 20:00
    time = datetime.now().time()
    nine_am = datetime.strptime("09:00:00", '%H:%M:%S').time()
    eight_pm = datetime.strptime("20:00:00", '%H:%M:%S').time()

    if (time > nine_am and time < eight_pm):
        return True
    else:
        return False

def add_to_lote(gm, content):

    lotes = Graph()
    lotes.parse(open('../Data/lotes'), format='turtle')

    # Obtenemos valores recibidos del content
    subject = gm.subjects(RDF.type, ECSDI.Pedido)
    for s in subject:
        city = gm.value(subject=s, predicate=ECSDI.Ciudad_Destino)
        priority = gm.value(subject=s, predicate=ECSDI.Prioridad_Entrega)
        logger.info(priority)
        peso = gm.value(subject=s, predicate=ECSDI.Peso_total_pedido)

        # Añadimos el pedido a un lote
        subjectLote = ECSDI['Lote_' + str(mss_cnt)]
        lotes.add((subjectLote, RDF.type, ECSDI.Lote))
        lotes.add((s, RDF.type, ECSDI.Pedido))
        lotes.add((s, ECSDI.Ciudad_Destino, Literal(city, datatype=XSD.string)))
        lotes.add((s, ECSDI.Prioridad_Entrega, Literal(priority, datatype=XSD.string)))
        lotes.add((s, ECSDI.Peso_total_pedido, Literal(peso, datatype=XSD.integer)))

        lotes.add((subjectLote, ECSDI.Pedidos_lote, URIRef(s)))

    lotes.serialize(destination='../Data/lotes', format='turtle')

def createSend():

    # Enviamos los lotes
    logger.info('Enviamos los lotes pendientes a enviar')

    # Obtenemos los lotes a enviar
    lotes = Graph()
    lotes.parse(open('../Data/lotes'), format='turtle')

    # Miramos todos los lotes a enviar 
    for lote in lotes.subjects(RDF.type, ECSDI.Lote):
        for pedido in lotes.objects(subject=lote, predicate=ECSDI.Pedidos_lote):
            city = lotes.value(subject=pedido, predicate=ECSDI.Ciudad_Destino)
            priority = lotes.value(subject=pedido, predicate=ECSDI.Prioridad_Entrega)
            peso = lotes.value(subject=pedido, predicate=ECSDI.Peso_total_pedido)

            # Miramos la prioridad de cada lote para asignar una fecha de entrega máxima
            if str(priority) == 'maxima':
                date = datetime.now() + timedelta(days=2)
            elif str(priority) == 'normal':
                date = datetime.now() + timedelta(days=5)

            gr = Graph()

            subjectTransport = ECSDI['Transportar_paquete_' + str(mss_cnt)]
            gr.add((subjectTransport, RDF.type, ECSDI.Transortar_Paquete))
            gr.add((subjectTransport, ECSDI.Terminio_maximo_entrega, Literal(date, datatype=XSD.dateTime)))
            gr.add((subjectTransport, ECSDI.Destino_pedido, Literal(city, datatype=XSD.sting)))
            gr.add((subjectTransport, ECSDI.Peso, Literal(peso, datatype=XSD.integer)))

            subjectT = ECSDI['Transportsta_'+ str(mss_cnt)]
            lotes.add((subjectT, RDF.type, ECSDI.Transportista))
            lotes.add((lote, ECSDI.Lote_Asignado_Transportista, URIRef(subjectT)))

            # Pedimos transporte
            requestTransport(gr, subjectTransport, pedido)

            # Eliminamos Lote enviado
            removeLote(lote)

def getTransportAgents():
    logger.info('Buscamos en el servicio de registro')

    global mss_cnt
    gmess = Graph()

    gmess.bind('foaf', FOAF)
    gmess.bind('dso', DSO)
    reg_obj = agn[LogisticCenterAgent.name + '-Search']
    gmess.add((reg_obj, RDF.type, ECSDI.Transport))
    gmess.add((reg_obj, DSO.AgentType, agn.ExternalTransportAgent))

    msg = build_message(gmess, perf=ACL.request,
                        sender=LogisticCenterAgent.uri,
                        receiver=DirectoryAgent.uri,
                        content=reg_obj,
                        msgcnt=mss_cnt)

    gr = send_message(msg, DirectoryAgent.address)
    mss_cnt += 1
    logger.info('Recibimos informacion de los agentes de Transporte.')

    dic = get_message_properties(gr)
    content = dic['content']
    transportistas = []

    for (s,p,o) in gr.triples((content, None, None)):
        if str(p).startswith("http://www.w3.org/1999/02/22-rdf-syntax-ns#_"):
            address = gr.value(subject=o, predicate=DSO.Address)
            url = gr.value(subject=o, predicate=DSO.Uri)
            name = gr.value(subject=o, predicate=FOAF.name)
            transportist = Agent(name, url, address, None)
            transportistas += [transportist]
    
    return transportistas

def requestTransport(gr, content, pedido):

    global mss_cnt
    
    logger.info('Pedimos transporte a los Agentes Externos de Transporte')

    #TransportAg = get_agent_info(agn.ExternalTransportAgent)
    agentes_transporte = getTransportAgents()
    TransportAg = None
    mejor_precio = float("inf")

    for Transport in agentes_transporte:
        logger.info("Mandamos una peticion de oferta de envio a un agente de Transporte" + str(Transport.name))
        gr_res = send_message(
            build_message(gr, 
            perf = ACL['call-for-proposal'], 
            sender = LogisticCenterAgent.uri, 
            receiver = Transport.uri,
            msgcnt = mss_cnt,
            content = content), Transport.address)
        

        msgdic  = get_message_properties(gr_res)
        performativa = msgdic['performative']

        if performativa == ACL['propose']:

            # El transportista nos envia un precio sobre el pedido propuesto enviado
            logger.info('Recibimos el precio ofrecido por el transportista')
            subjet = gr_res.subjects(RDF.type, ECSDI.Propuesta_transporte)
            for s in subjet:
                precio = float(gr_res.value(subject=s, predicate=ECSDI.Precio_envio))
            
            if precio < mejor_precio:
                mejor_precio = precio
                TransportAg = Transport

    for trans in agentes_transporte:
        if trans != TransportAg:
            logger.info("Informamos al agente " + str(trans.name) + " que no ha sido elegido.")
            gr = send_message(build_message(Graph(), 
                perf = ACL['reject-proposal'], 
                sender = LogisticCenterAgent.uri, 
                receiver = msgdic['sender'],
                msgcnt = mss_cnt), trans.address)

    # Contra oferta sobre el precio propuesto por el transportista
    logger.info('El Centro Logístico hace una contra oferta al transportista elegido.')

    nuevo_precio = precio - (precio * (random.randint(1,15))/100)

    g = Graph()

    subjectGr = ECSDI['Enviar_controferta_' + str(mss_cnt)]
    g.add((subjectGr, RDF.type, ECSDI.Enviar_contraoferta))
    g.add((subjectGr, ECSDI.Precio_envio, Literal(precio, datatype=XSD.float)))
    g.add((subjectGr, ECSDI.Precio_contraoferta, Literal(nuevo_precio, datatype=XSD.float)))

    gr = send_message(build_message(g, 
        perf = ACL.request, 
        sender = LogisticCenterAgent.uri, 
        receiver = msgdic['sender'],
        msgcnt = mss_cnt,
        content = subjectGr), TransportAg.address)

    msgdic = get_message_properties(gr)
    performativa = msgdic['performative']

    if performativa == ACL['accept']:
        logger.info('El transportista elegido ha aceptado la contra oferta.')

        gr = send_message(build_message(Graph(), 
        perf = ACL['inform'], 
        sender = LogisticCenterAgent.uri, 
        receiver = msgdic['sender'],
        msgcnt = mss_cnt), TransportAg.address)

    elif performativa == ACL['reject']:
        logger.info('El transportista elegido no ha aceptado la contra oferta.')

        gr = send_message(build_message(Graph(), 
        perf = ACL['inform'], 
        sender = LogisticCenterAgent.uri, 
        receiver = msgdic['sender'],
        msgcnt = mss_cnt), TransportAg.address)

    elif performativa == ACL['propose']:
        logger.info('El transportista elegido ha enviado una nueva contra oferta.')

        gr = send_message(build_message(Graph(), 
        perf = ACL['inform'], 
        sender = LogisticCenterAgent.uri, 
        receiver = msgdic['sender'],
        msgcnt = mss_cnt), TransportAg.address)

    logger.info('El pedido ha sido enviado correctamente.')
    logger.info('Enviamos un mensaje a Sales Procesor para informar que el pedido ha sido enviado.')

    graph = Graph()
    sub = ECSDI['Listo_para_pagar_' + str(mss_cnt)] 
    graph.add((sub, RDF.type, ECSDI.Listo_para_pagar))
    graph.add((sub, ECSDI.Pedido_enviado, Literal(pedido, datatype=XSD.string)))

    SalesProcessorAg = get_agent_info(agn.SalesProcessorAgent)

    gr = send_message(build_message(graph, 
            perf = ACL.request, 
            sender = LogisticCenterAgent.uri, 
            receiver = SalesProcessorAg.uri,
            msgcnt = mss_cnt,
            content = sub), SalesProcessorAg.address)      

            

def removeLote(url):

    lotes = Graph()
    lotes.parse(open('../Data/lotes'), format='turtle')

    for s in lotes.objects(subject=url, predicate=ECSDI.Pedidos_lote):
        lotes.remove((s,None,None))
             
    # Eliminamos el lote ya enviado
    lotes.remove((url, None, None))

    lotes.serialize(destination='../Data/lotes', format='turtle')



def get_agent_info(type):

    global mss_cnt
    logger.info('Buscamos en el servicio de registro')

    gmess = Graph()

    gmess.bind('foaf', FOAF)
    gmess.bind('dso', DSO)
    reg_obj = agn[LogisticCenterAgent.name + '-Search']
    gmess.add((reg_obj, RDF.type, DSO.Search))
    gmess.add((reg_obj, DSO.AgentType, type))

    msg = build_message(gmess, perf=ACL.request,
                        sender=LogisticCenterAgent.uri,
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

    

if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(queue,))
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()
    logger.info('The End')
