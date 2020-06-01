# -*- coding: utf-8 -*-
"""
filename: SimpleInfoAgent
Antes de ejecutar hay que añadir la raiz del proyecto a la variable PYTHONPATH
Agente que se registra como agente de hoteles y espera peticiones
@author: javier
"""

from multiprocessing import Process, Queue
import socket
import argparse

from flask import Flask, request
from rdflib import Graph, Namespace, Literal
from rdflib.namespace import FOAF, RDF, XSD

from AgentUtil.OntoNamespaces import ACL, DSO, ECSDI
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.ACLMessages import build_message, send_message, get_message_properties
from AgentUtil.Agent import Agent
from AgentUtil.Logging import config_logger

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
    port = 9009
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
TreasurerAgent = Agent('TreasurerAgent',
                  agn.TreasurerAgent,
                  'http://%s:%d/comm' % (hostname, port),
                  'http://%s:%d/Stop' % (hostname, port))

# Directory agent address
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))

# Global dsgraph triplestore
dsgraph = Graph()

# Cola de comunicacion entre procesos
cola1 = Queue()


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
    reg_obj = agn[TreasurerAgent.name + '-Register']
    gmess.add((reg_obj, RDF.type, DSO.Register))
    gmess.add((reg_obj, DSO.Uri, TreasurerAgent.uri))
    gmess.add((reg_obj, FOAF.name, Literal(TreasurerAgent.name)))
    gmess.add((reg_obj, DSO.Address, Literal(TreasurerAgent.address)))
    gmess.add((reg_obj, DSO.AgentType, agn.TreasurerAgent))

    # Lo metemos en un envoltorio FIPA-ACL y lo enviamos
    gr = send_message(
        build_message(gmess, perf=ACL.request,
                      sender=TreasurerAgent.uri,
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
    reg_obj = agn[TreasurerAgent.name + '-search']
    gmess.add((reg_obj, RDF.type, DSO.Search))
    gmess.add((reg_obj, DSO.AgentType, type))

    msg = build_message(gmess, perf=ACL.request,
                        sender=TreasurerAgent.uri,
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
                        sender=TreasurerAgent.uri,
                        receiver=ragn.uri,
                        msgcnt=mss_cnt,
                        content=contentRes)
    gr = send_message(msg, ragn.address)
    mss_cnt += 1
    logger.info('Recibimos respuesta a la peticion al servicio de informacion')

    return gr

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

    logger.info('Peticion de informacion recibida')

    # Extraemos el mensaje y creamos un grafo con el
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message)

    msgdic = get_message_properties(gm)

    # Comprobamos que sea un mensaje FIPA ACL
    if msgdic is None:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(), ACL['not-understood'], sender=TreasurerAgent.uri, msgcnt=mss_cnt)
    else:
        # Obtenemos la performativa
        perf = msgdic['performative']

        if perf != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(), ACL['not-understood'], sender=TreasurerAgent.uri, msgcnt=mss_cnt)
        else:
            # Extraemos el objeto del contenido que ha de ser una accion de la ontologia de acciones del agente
            # de registro

            # Averiguamos el tipo de la accion
            if 'content' in msgdic:
                content = msgdic['content']
                accion = gm.value(subject=content, predicate=RDF.type)

                banco = get_agent_info(agn.BankAgent)
                g = Graph()

                # Cobrar el importe de un pedido
                if accion == ECSDI.Cobrar_pedido:
                    logger.info("Se ha pedido cobrar un pedido.")
                    import_tot = 0.0
                    # en el caso que haya más de un producto externo, lo guardamos en una lista
                    index = 0
                    extSeller_pos = {}
                    info_ext = []

                    # coger la información de pago y el importe y comunicarse con el agente externo banco
                    for s in gm.subjects(RDF.type, ECSDI.Pedido):
                        info_pago_usuario = str(gm.value(subject=s, predicate=ECSDI.Informacion_Pago))
                        import_tot = float(gm.value(subject=s, predicate=ECSDI.Precio_total_pedido))

                        # miramos los productos externos y nos guardamos la informacion de pago (si es el caso)
                        for prod_ext in gm.subjects(RDF.type, ECSDI.Producto_externo):
                            # cogemos la información del vendedor externo
                            for vend_ext in gm.objects(subject=prod_ext, predicate=ECSDI.Vendido_por):
                                info_pago_ext = str(gm.value(subject=vend_ext, predicate=ECSDI.Forma_pago))
                                # si no tenemos el vendedor guardado, lo añadimos con la información necesaria
                                if vend_ext not in extSeller_pos:
                                    extSeller_pos[vend_ext] = index
                                    subject_imp = {}
                                    subject_imp['importe'] = float(gm.value(subject=prod_ext, predicate=ECSDI.Precio))
                                    #cogemos la información de pago
                                    subject_imp['cuenta'] = info_pago_ext
                                    info_ext.append(subject_imp)
                                    index += 1
                                # si el vendedor ya lo tenemos guardado
                                elif vend_ext in extSeller_pos:
                                    subject_imp = info_ext[extSeller_pos[vend_ext]]
                                    subject_imp['importe'] += float(gm.value(subject=prod_ext, predicate=ECSDI.Precio))
                                    info_ext[extSeller_pos[vend_ext]] = subject_imp

                    # Realizamos el cobro al cliente de todo a la tienda
                    logger.info("Se cobra el importe total del pedido .")
                    subject_trans = ECSDI["Realizar_transferencia_" + str(mss_cnt)]
                    g.add((subject_trans, RDF.type, ECSDI.Realizar_transferencia))
                    g.add((subject_trans, ECSDI.Cuenta_origen, Literal(info_pago_usuario, datatype=XSD.string)))
                    g.add((subject_trans, ECSDI.Cuenta_destino, Literal("MiTienda000", datatype=XSD.string)))
                    g.add((subject_trans, ECSDI.Importe, Literal(import_tot, datatype=XSD.float)))
                    res = send_message_to_agent(g, banco, subject_trans)

                    # si se han encontrado productos externos, procedemos a cobrar el importe para cada vendedor externo
                    if info_ext:
                        ga = Graph()
                        logger.info("Se cobran los importes de productos externos.")
                        # por cada vendedor externo diferente le cobramos lo correspondido
                        for item in info_ext:
                            subject_trans = ECSDI["Realizar_transferencia_" + str(mss_cnt)]
                            ga.add((subject_trans, RDF.type, ECSDI.Realizar_transferencia))
                            ga.add((subject_trans, ECSDI.Cuenta_origen, Literal("MiTienda000", datatype=XSD.string)))
                            ga.add((subject_trans, ECSDI.Cuenta_destino, Literal(item['cuenta'], datatype=XSD.string)))
                            ga.add((subject_trans, ECSDI.Importe, Literal(item['importe'], datatype=XSD.float)))
                            res = send_message_to_agent(ga, banco, subject_trans)

                    # una vez cobrados los importes necesarios, respondemos con un ACK
                    gr = build_message(Graph(),
                        ACL['inform-done'],
                        sender=TreasurerAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'], )

                elif accion == ECSDI.Devolver_importe:
                    logger.info("Se ha pedido devolver un importe.")

                    subject_trans = ECSDI["Realizar_transferencia_" + str(mss_cnt)]
                    # coger la información de pago y el importe y comunicarse con el agente externo banco
                    for s in gm.subjects(RDF.type, ECSDI.Devolver_importe):
                        info_pago_usuario = str(gm.value(subject=s, predicate=ECSDI.Forma_pago))
                        g.add((subject_trans, ECSDI.Cuenta_destino, Literal(info_pago_usuario, datatype=XSD.string)))

                    # obtenemos el importe del producto 
                    for producto in gm.objects(subject=content, predicate=ECSDI.Producto_a_Devolver):
                        g.add((subject_trans, RDF.type, ECSDI.Realizar_transferencia))

                        importe = float(gm.value(subject=producto, predicate=ECSDI.Precio))
                        g.add((subject_trans, ECSDI.Importe, Literal(importe, datatype=XSD.float)))
                        g.add((subject_trans, ECSDI.Cuenta_origen, Literal("MiTienda000", datatype=XSD.string)))
                        
                        # miramos el tipo de producto, para saber cual es la cuenta origen
                        prod_type = gm.value(subject=producto, predicate=RDF.type)
                        
                        # si es un producto externo debemos conseguir el dinero del vendedor externo primero
                        if prod_type == ECSDI.Producto_externo:
                            ge = Graph()
                            # obtenemos la información de pago del vendedor externo
                            for vend_ext in gm.objects(subject=producto, predicate=ECSDI.Vendido_por):
                                info_pago_ext = str(gm.value(subject=vend_ext, predicate=ECSDI.Forma_pago))
                                subject_trans = ECSDI["Realizar_transferencia_" + str(mss_cnt)]
                                ge.add((subject_trans, RDF.type, ECSDI.Realizar_transferencia))
                                ge.add((subject_trans, ECSDI.Cuenta_origen, Literal(info_pago_ext, datatype=XSD.string)))
                                ge.add((subject_trans, ECSDI.Cuenta_destino, Literal("MiTienda000", datatype=XSD.string)))
                                ge.add((subject_trans, ECSDI.Importe, Literal(importe, datatype=XSD.float)))
                                res = send_message_to_agent(ge, banco, subject_trans)

                        # una vez conseguido el dinero del vendedor externo, se lo pagamos al cliente
                        res = send_message_to_agent(g, banco, subject_trans)

                    # una vez se ha realizado la transferencia, respondemos con un ACK
                    gr = build_message(Graph(),
                        ACL['inform-done'],
                        sender=TreasurerAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'], )

                else:
                    gr = build_message(Graph(),
                        ACL['not-understood'],
                        sender=TreasurerAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'], )
                
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
    # Registramos el agente
    gr = register_message()


if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()

    # Ponemos en marcha el servidor
    app.run(host=hostname, port=port)

    # Esperamos a que acaben los behaviors
    ab1.join()
    logger.info('The End')