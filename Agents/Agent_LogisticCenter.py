# -*- coding: utf-8 -*-
"""

    AGENTE CENTRO LOGISTICO

"""

from multiprocessing import Process, Queue
import socket
import argparse

from flask import Flask, render_template, request
from rdflib import Graph, Namespace
from rdflib.namespace import FOAF, RDF
import requests

from AgentUtil.OntoNamespaces import ACL, DSO
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

# Datos del Agente
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
    gmess.add((reg_obj, DSO.AgentType, LogisticCenterAgent.uri))

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
    return "Hola"


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


if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(queue,))
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()
    logger.info('The End')
