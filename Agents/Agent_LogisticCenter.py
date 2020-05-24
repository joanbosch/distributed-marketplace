# -*- coding: utf-8 -*-
"""

    AGENTE CENTRO LOGISTICO

"""

from multiprocessing import Process, Queue
import socket
import argparse
from datetime import datetime

from flask import Flask, render_template, request
from rdflib import Graph, Namespace, Literal, XSD
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
    gmess.add((reg_obj, DSO.AgentType, ECSDI.Centro_Logistico))

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

    


#Agente Centro Logistico no se si te iface ( jo crec que s'ha de borrar )
@app.route("/iface", methods=['GET', 'POST'])
def browser_iface():
    """
    Permite la comunicacion con el agente via un navegador
    via un formulario
    """
    if request.method == 'GET':
        return render_template('iface.html')
    else:
        user = request.form['username']
        mess = request.form['message']
        return render_template('riface.html', user=user, mess=mess)

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
        #Obtenemos la performativa
        perf = msgdic['performative']
        env_url = None
        if perf == ACL['request']:
            #Contenido del pedido: ciudad destino + prioridad entrega
            logger.info('Peticion de envío de pedido')
            #Crear lot amb el graph de lots on tingui guardats altres pedidos amb: mateixa ciutat + prioritat envio
            add_to_lote(gm, msgdic['content'])
            #Comprobar si estem ciertas horas del dia y enviar lote
            if time_to_send():
                logger.info('Se envian lotes a los transportistas')
                enviosUrl = createSend()

                envios = Graph()
                envios.parse(open('../data/enviaments'), format='turtle')
                for env in enviosUrl:
                    fecha = envios.value(subject=env, predicate=ECSDI.Fecha_Entrega)
                    peso = envios.value(subject=env, predicate=ECSDI.Peso)
                    env_url = env
                    requestTransport(fecha,peso)

        elif perf == ACL['proposal']:
            #El transportista nos envia un precio sobre el pedido propuesto enviado
            logger.info('Recibimos el precio ofrecido por el transportista')
            precio = gm.value(subject=msgdic['content'], predicate=ECSDI.Precio_Transporte)
            if precio < 100:
                logger.info('Aceptamos el precio propuesto por el transportista')
                gr = send_message(
                    build_message(gr, 
                    perf = ACL['accept-proposal'], 
                    sender = LogisticCenterAgent.uri, 
                    receiver = msgdic['sender'],
                    msgcnt = mss_cnt), msgdic['sender'])
                removeLote(env_url)
            else:
                logger.info('No aceptamos el precio propuesto por el transportista')
                gr = send_message(
                    build_message(gr, 
                    perf = ACL['reject-proposal'], 
                    sender = LogisticCenterAgent.uri, 
                    receiver = msgdic['sender'],
                    msgcnt = mss_cnt), msgdic['sender'])

        elif perf == ACL['refuse']:
            #enviar a un altre transportista el envio que o sha pogut enviar
            logger.info('Buscamos otro transportista que pueda realizar el envio')

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
    fin = False
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

def time_to_send():
    time = datetime.now().time()
    t="10:00:00"
    ten_am = datetime.strptime(t, '%H:%M:%S').time()
    t="12:00:00"
    twelve_pm = datetime.strptime(t, '%H:%M:%S').time()
    t="16:00:00"
    four_pm = datetime.strptime(t, '%H:%M:%S').time()
    t="18:00:00"
    six_pm = datetime.strptime(t, '%H:%M:%S').time()

    if (time > ten_am and time < twelve_pm) or (time > four_pm and time < six_pm):
        return True
    else:
        return False

def add_to_lote(gm, content):
    #Añadimos el envio a un lote
    lotes = Graph()
    lotes.parse(open('../data/lotes'), format='turtle')
    #Obtenemos valores recibidos del content
    city = gm.value(subject=content, predicate=ECSDI.Ciudad_Destino)
    priority = gm.value(subject=content, predicate=ECSDI.Prioridad_Enterga)
    #Numero de envio random para asignar un sujeto
    subjectLote = ECSDI['Lote_' + str(random.randint(1, sys.float_info.max))]
    lotes.add((subjectLote, RDF.type, ECSDI.Lote))
    lotes.add((subjectLote, ECSDI.Ciudad_Destino, Literal(city, datatype=XSD.string)))
    lotes.add((subjectLote, ECSDI.Prioridad_Entrega, Literal(priority, datatype=XSD.string)))

    lotes.serialize(destination='../data/lotes', format='turtle')

def createDate(date):
    return (date - datetime.datetime.utcfromtimestamp(0)).total_seconds() * 1000.0

def createSend():
    #eliminar de lotes el que enviem
    envios = Graph()
    envios.parse(open('../data/enviaments'), format='turtle')
    lotes = Graph()
    lotes.parse(open('../data/lotes'), format='turtle')
    lista_envios = []
    #afagar els lotes de maxima prioritat
    for lote in lotes.subjects(RDF.type, ECSDI.Lote):
        subjectEnvio = ECSDI['Envio_' + str(random.randint(1, sys.float_info.max))]
        date = createDate(datetime.datetime.utcnow() + datetime.timedelta(days=9))
        peso = random.randrange(1, 100)
        for predicate, objects in lotes[lote]:
            if predicate == ECSDI.Prioridad_Entrega:
                if objects == 'maxima':
                    enviar = True
                    #Creem un envio amb prioritat maxima
                    envios.add((subjectEnvio, RDF.type, ECSDI.Envio))
                    envios.add((subjectEnvio, ECSDI.Fecha_Entrega, Literal(date, datatype=XSD.float)))
            if enviar == True:
                if predicate == ECSDI.Ciudad_Destino:
                    envios.add((subjectEnvio, ECSDI.Ciudad_Destino, objects))
                    envios.add((subjectEnvio, ECSDI.Peso, Literal(peso, datatype=XSD.integer)))
        lista_envios.append(subjectEnvio)

    #agafar els lotes de normal prioritat
    for lote in lotes.subjects(RDF.type, ECSDI.Lote):       
        subjectEnvio = ECSDI['Envio_' + str(random.randint(1, sys.float_info.max))]
        date = createDate(datetime.datetime.utcnow() + datetime.timedelta(days=9))
        peso = random.randrange(1, 100)
        for predicate, objects in lotes[lote]:
            if predicate == ECSDI.Prioridad_Entrega:
                if objects == 'normal':
                    enviar = True
                    #Creem un envio amb prioritat maxima
                    envios.add((subjectEnvio, RDF.type, ECSDI.Envio))
                    envios.add((subjectEnvio, ECSDI.Fecha_Entrega, Literal(date, datatype=XSD.float)))
            if enviar == True:
                if predicate == ECSDI.Ciudad_Destino:
                    envios.add((subjectEnvio, ECSDI.Ciudad_Destino, objects))
                    envios.add((subjectEnvio, ECSDI.Peso, Literal(peso, datatype=XSD.integer)))
        lista_envios.append(subjectEnvio)

    return lista_envios



def requestTransport(date, peso):

    global mss_cnt
    
    logger.info('Pedimos transporte a los Agentes Externos de Transporte')

    content = ECSDI['Peticio_transport' + str(mss_cnt)]

    gr = Graph()
    gr.add((content, RDF.type, ECSDI.Transportar_Paquete))

    gr.add((content, ECSDI.Terminio_maximo_entrega, Literal(date, datatype=XSD.float)))
    gr.add((content, ECSDI.Peso, Literal(peso, datatype=XSD.float)))

    TransportAg = get_agent_info(agn.ExternalTransportAgent , DirectoryAgent, LogisticCenterAgent, mss_cnt)

    gr = send_message(
        build_message(gr, 
        perf = ACL.proposal, 
        sender = LogisticCenterAgent.uri, 
        receiver = TransportAg.uri,
        msgcnt = mss_cnt,
        content = content), TransportAg.address)

def removeLote(url):
    lotes = Graph()
    lotes.parse(open('../data/lotes'), format='turtle')

    #eliminamos el lote ya enviado
    lotes.remove((url, None, None))

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
    ab1 = Process(target=agentbehavior1, args=(queue,))
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()
    logger.info('The End')
