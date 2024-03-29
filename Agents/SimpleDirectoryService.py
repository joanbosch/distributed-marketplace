# -*- coding: utf-8 -*-
"""
filename: SimpleDirectoryAgent

Antes de ejecutar hay que añadir la raiz del proyecto a la variable PYTHONPATH

Agente que lleva un registro de otros agentes

Utiliza un registro simple que guarda en un grafo RDF

El registro no es persistente y se mantiene mientras el agente funciona

Las acciones que se pueden usar estan definidas en la ontología
directory-service-ontology.owl

"""

from multiprocessing import Process, Queue
import socket
import argparse

from flask import Flask, request, render_template
from rdflib import Graph, RDF, Namespace, RDFS, BNode, URIRef
from rdflib.namespace import FOAF

from AgentUtil.OntoNamespaces import ACL, DSO, ECSDI
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.Agent import Agent
from AgentUtil.ACLMessages import build_message, get_message_properties
from AgentUtil.Logging import config_logger

__author__ = 'javier'

# Definimos los parametros de la linea de comandos
parser = argparse.ArgumentParser()
parser.add_argument('--open', help="Define si el servidor est abierto al exterior o no", action='store_true',
                    default=False)
parser.add_argument('--port', type=int, help="Puerto de comunicacion del agente")

# Logging
logger = config_logger(level=1)

# parsing de los parametros de la linea de comandos
args = parser.parse_args()

# Configuration stuff
if args.port is None:
    port = 9000
else:
    port = args.port

if args.open:
    hostname = '0.0.0.0'
else:
    hostname = socket.gethostname()

# Directory Service Graph
dsgraph = Graph()

# Vinculamos todos los espacios de nombre a utilizar
dsgraph.bind('acl', ACL)
dsgraph.bind('rdf', RDF)
dsgraph.bind('rdfs', RDFS)
dsgraph.bind('foaf', FOAF)
dsgraph.bind('dso', DSO)

agn = Namespace("http://www.agentes.org#")
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (hostname, port),
                       'http://%s:%d/Stop' % (hostname, port))
app = Flask(__name__, template_folder="../Templates")
mss_cnt = 0

cola1 = Queue()  # Cola de comunicacion entre procesos


@app.route("/Register")
def register():
    """
    Entry point del agente que recibe los mensajes de registro
    La respuesta es enviada al retornar la funcion,
    no hay necesidad de enviar el mensaje explicitamente

    Asumimos una version simplificada del protocolo FIPA-request
    en la que no enviamos el mesaje Agree cuando vamos a responder

    :return:
    """

    def process_register():
        # Si la hay extraemos el nombre del agente (FOAF.name), el URI del agente
        # su direccion y su tipo

        logger.info('Peticion de registro')

        agn_add = gm.value(subject=content, predicate=DSO.Address)
        agn_name = gm.value(subject=content, predicate=FOAF.name)
        agn_uri = gm.value(subject=content, predicate=DSO.Uri)
        agn_type = gm.value(subject=content, predicate=DSO.AgentType)

        # Añadimos la informacion en el grafo de registro vinculandola a la URI
        # del agente y registrandola como tipo FOAF.Agent
        dsgraph.add((agn_uri, RDF.type, FOAF.Agent))
        dsgraph.add((agn_uri, FOAF.name, agn_name))
        dsgraph.add((agn_uri, DSO.Address, agn_add))
        dsgraph.add((agn_uri, DSO.AgentType, agn_type))

        # Generamos un mensaje de respuesta
        return build_message(Graph(),
            ACL.confirm,
            sender=DirectoryAgent.uri,
            receiver=agn_uri,
            msgcnt=mss_cnt)

    def process_search():
        # Asumimos que hay una accion de busqueda que puede tener
        # diferentes parametros en funcion de si se busca un tipo de agente
        # o un agente concreto por URI o nombre
        # Podriamos resolver esto tambien con un query-ref y enviar un objeto de
        # registro con variables y constantes

        # Solo consideramos cuando Search indica el tipo de agente
        # Buscamos una coincidencia exacta
        # Retornamos el primero de la lista de posibilidades

        logger.info('Peticion de busqueda')

        agn_type = gm.value(subject=content, predicate=DSO.AgentType)
        rsearch = dsgraph.triples((None, DSO.AgentType, agn_type))
        print(rsearch)
        if rsearch is not None:
            agn_uri = next(rsearch)[0]
            agn_add = dsgraph.value(subject=agn_uri, predicate=DSO.Address)
            gr = Graph()
            gr.bind('dso', DSO)
            rsp_obj = agn['Directory-response']
            gr.add((rsp_obj, DSO.Address, agn_add))
            gr.add((rsp_obj, DSO.Uri, agn_uri))
            return build_message(gr,
                                 ACL.inform,
                                 sender=DirectoryAgent.uri,
                                 msgcnt=mss_cnt,
                                 receiver=agn_uri,
                                 content=rsp_obj)
        else:
            # Si no encontramos nada retornamos un inform sin contenido
            return build_message(Graph(),
                ACL.inform,
                sender=DirectoryAgent.uri,
                msgcnt=mss_cnt)

    def process_search_transport():
        # Asumimos que hay una accion de busqueda que puede tener
        # diferentes parametros en funcion de si se busca un tipo de agente
        # o un agente concreto por URI o nombre
        # Podriamos resolver esto tambien con un query-ref y enviar un objeto de
        # registro con variables y constantes

        # Solo consideramos cuando Search indica el tipo de agente
        # Buscamos una coincidencia exacta
        # Retornamos el primero de la lista de posibilidades

        logger.info('Peticion de busqueda')

        agn_type = gm.value(subject=content, predicate=DSO.AgentType)
        rsearch = dsgraph.triples((None, DSO.AgentType, agn_type))
        print(rsearch)

        # Debemos buscar todos los transportistas registrados y devolver sus datos.
        gr = Graph()
        gr.bind('dso', DSO)

        all_transp = BNode()
        gr.add((all_transp, RDF.type, RDF.Bag))
        i = 0
        for agn_uri in rsearch:
            logger.info("Añadiendo un nuevo agente de transporte.")
            
            agn_name = dsgraph.value(subject=agn_uri[0], predicate=FOAF.name)
            logger.info("Obteniendo Nombre del Agente." + str(agn_name))
            logger.info("Obteniendo URI del agente.")
            agn_add = dsgraph.value(subject=agn_uri[0], predicate=DSO.Address)
            
            logger.info("Añadiendo parametros al grafo.")
            rsp_obj = agn['Directory-response' + str(i)]
            logger.info("Añadiendo Direccion del agente al grafo.")
            gr.add((rsp_obj, DSO.Address, agn_add))
            logger.info("Añadiendo URI del Agente al grafo.")
            gr.add((rsp_obj, DSO.Uri, agn_uri[0]))
            logger.info("Agadiendo Nombre del agente al Grafo")
            gr.add((rsp_obj, FOAF.name, agn_name))
            logger.info("Añadiendo Bag del agente al Grafo")
            gr.add((all_transp, URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#_'+ str(i)), rsp_obj))
            
            logger.info("Siguiente Agente")
            i += 1

        logger.info("Salimos del bucle")
        if rsearch is not None:
            logger.info("Montamos el mensaje.")
            return build_message(gr,
                                 ACL.inform,
                                 sender=DirectoryAgent.uri,
                                 msgcnt=mss_cnt,
                                 content=all_transp)
        else:
            # Si no encontramos nada retornamos un inform sin contenido
            logger.info("Montamos un mensaje sin contenido.")
            return build_message(Graph(),
                ACL.inform,
                sender=DirectoryAgent.uri,
                msgcnt=mss_cnt)

    global dsgraph
    global mss_cnt
    # Extraemos el mensaje y creamos un grafo con él
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message)

    msgdic = get_message_properties(gm)

    # Comprobamos que sea un mensaje FIPA ACL
    if not msgdic:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(),
            ACL['not-understood'],
            sender=DirectoryAgent.uri,
            msgcnt=mss_cnt)
    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                ACL['not-understood'],
                sender=DirectoryAgent.uri,
                msgcnt=mss_cnt)
        else:
            # Extraemos el objeto del contenido que ha de ser una accion de la ontologia
            # de registro
            content = msgdic['content']
            # Averiguamos el tipo de la accion
            accion = gm.value(subject=content, predicate=RDF.type)

            # Accion de registro
            if accion == DSO.Register:
                gr = process_register()
            # Accion de busqueda
            elif accion == DSO.Search:
                gr = process_search()
            # No habia ninguna accion en el mensaje
            elif accion == ECSDI.Transport:
                gr = process_search_transport()
            else:
                gr = build_message(Graph(),
                        ACL['not-understood'],
                        sender=DirectoryAgent.uri,
                        msgcnt=mss_cnt)
    mss_cnt += 1
    return gr.serialize(format='xml')


@app.route('/Info')
def info():
    """
    Entrada que da informacion sobre el agente a traves de una pagina web
    """
    global dsgraph
    global mss_cnt

    return render_template('info.html', nmess=mss_cnt, graph=dsgraph.serialize(format='turtle'))


@app.route("/Stop")
def stop():
    """
    Entrada que para el agente
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
    Behaviour que simplemente espera mensajes de una cola y los imprime
    hasta que llega un 0 a la cola
    """
    """
    fin = False
    while not fin:
        while cola.empty():
            pass
        v = cola.get()
        if v == 0:
            print(v)
            return 0
        else:
            print(v)
    """


if __name__ == '__main__':
    # Ponemos en marcha los behaviours como procesos
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()

    # Ponemos en marcha el servidor Flask
    app.run(host=hostname, port=port, debug=True)

    ab1.join()
    logger.info('The End')
