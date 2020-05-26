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
    port = 9004
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
SalesProcessorAgent = Agent('SalesProcessorAgent',
                       agn.SalesProcessorAgent,
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
    reg_obj = agn[SalesProcessorAgent.name + '-Register']
    gmess.add((reg_obj, RDF.type, DSO.Register))
    gmess.add((reg_obj, DSO.Uri, SalesProcessorAgent.uri))
    gmess.add((reg_obj, FOAF.name, Literal(SalesProcessorAgent.name)))
    gmess.add((reg_obj, DSO.Address, Literal(SalesProcessorAgent.address)))
    gmess.add((reg_obj, DSO.AgentType, ECSDI.Procesador_Compras)) # Això s'hauria de revisar. Si deixem el tipus a ECSDI.Procesador_Compras caldria afegir-ho a la ontologia.

    # Lo metemos en un envoltorio FIPA-ACL y lo enviamos
    gr = send_message(
        build_message(gmess, perf=ACL.request,
                      sender=SalesProcessorAgent.uri,
                      receiver=DirectoryAgent.uri,
                      content=reg_obj,
                      msgcnt=mss_cnt),
        DirectoryAgent.address)
    mss_cnt += 1

    return gr

@app.route("/comm")
def comunicacion():
    """
    Entrypoint de comunicacion
    Quan tot això funcioni, respondrà a peticions de cerca i registrarà comandes
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
        gr = build_message(Graph(), ACL['not-understood'], sender=SalesProcessorAgent.uri, msgcnt=mss_cnt)
    else:
        # Obtenemos la performativa
        perf = msgdic['performative']

        if perf != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(), ACL['not-understood'], sender=SalesProcessorAgent.uri, msgcnt=mss_cnt)
        else:
            # Extraemos el objeto del contenido que ha de ser una accion de la ontologia de acciones del agente
            # de registro

            # Averiguamos el tipo de la accion
            if 'content' in msgdic:
                content = msgdic['content']
                accion = gm.value(subject=content, predicate=RDF.type)
                
                # Search products action
                if accion == ECSDI.Buscar_productos:
                    searchFilters = gm.objects(content, ECSDI.Filtro_busqueda)
                    searchFilters_dict = {}
                    for filter in searchFilters:
                        if gm.value(subject=filter, predicate=RDF.type) == ECSDI.Filtrar_nombre:
                            name = gm.value(subject=filter, predicate=ECSDI.Nombre)
                            logger.info('Nombre: ' + name)
                            searchFilters_dict['name'] = name
                        elif gm.value(subject=filter, predicate=RDF.type) == ECSDI.Filtrar_marca:
                            brand = gm.value(subject=filter, predicate=ECSDI.Marca)
                            logger.info('Marca: ' + brand)
                            searchFilters_dict['brand'] = brand
                        elif gm.value(subject=filter, predicate=RDF.type) == ECSDI.Filtrar_tipo:
                            prod_type = gm.value(subject=filter, predicate=ECSDI.Tipo)
                            logger.info('Tipo: ' + prod_type)
                            searchFilters_dict['prod_type'] = prod_type
                        elif gm.value(subject=filter, predicate=RDF.type) == ECSDI.Filtrar_precio:
                            min_price = gm.value(subject=filter, predicate=ECSDI.Precio_minimo)
                            max_price = gm.value(subject=filter, predicate=ECSDI.Precio_maximo)
                            if min_price:
                                logger.info('Precio minimo: ' + min_price)
                                searchFilters_dict['min_price'] = min_price.toPython()
                            if max_price:
                                logger.info('Precio maximo: ' + max_price)
                                searchFilters_dict['max_price'] = max_price.toPython()
                        elif gm.value(subject=filter, predicate=RDF.type) == ECSDI.Filtrar_vendedores_externos:
                            external_prod = gm.value(subject=filter, predicate=ECSDI.Incluir_productos_externos)
                            internal_prod = gm.value(subject=filter, predicate=ECSDI.Incluir_productos_tienda)
                            if external_prod and external_prod == False: # potser al == cal afegir .toPython()
                                logger.info('No se incluyen productos externos')
                                searchFilters_dict['exclude_external_prod'] = True
                            if internal_prod and internal_prod == False: # potser al == cal afegir .toPython()
                                logger.info('No se incluyen productos internos')
                                searchFilters_dict['exclude_internal_prod'] = True

                    gr = build_message(searchProducts(**searchFilters_dict),
                        ACL['inform-result'],
                        sender=SalesProcessorAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'])
                
                # Buy products action
                elif accion == ECSDI.Procesar_Compra:
                    logger.info('Recibida peticion compra')
                    gOrder = recordNewOrder(gm)
                    logger.info('Asignamos envio a centro logistico')
                    assignToLogisticCenter(gOrder)

                    gr = build_message(Graph(),
                        ACL['inform-done'],
                        sender=SalesProcessorAgent.uri,
                        msgcnt=mss_cnt,
                        receiver=msgdic['sender'])

                else:
                    gr = build_message(Graph(),
                        ACL['not-understood'],
                        sender=SalesProcessorAgent.uri,
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

def searchProducts(name=None, brand=None, prod_type=None, min_price=0.0, max_price=sys.float_info.max, exclude_external_prod=None, exclude_internal_prod=None):
    graph = Graph()
    ontologyFile = open('../Data/products')
    graph.parse(ontologyFile, format='turtle')

    first_filter = first_prod_class = 0
    query = """
        prefix rdf:<http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        prefix xsd:<http://www.w3.org/2001/XMLSchema#>
        prefix ecsdi:<http://www.semanticweb.org/joan/ontologies/2020/3/practicaECSDI#>
        prefix owl:<http://www.w3.org/2002/07/owl#>
        SELECT DISTINCT ?producto ?nombre ?marca ?tipo ?precio ?peso
        where {
        """

    if exclude_external_prod is None:
        query += """{ ?producto rdf:type ecsdi:Producto_exteno }"""
        first_prod_class = 1
    if exclude_internal_prod is None:
        if first_prod_class == 1:
            query += """ UNION """
        query += """{ ?producto rdf:type ecsdi:Producto_interno }"""

    query += """ .
            ?producto ecsdi:Nombre ?nombre .
            ?producto ecsdi:Marca ?marca .
            ?producto ecsdi:Tipo ?tipo .
            ?producto ecsdi:Precio ?precio .
            ?producto ecsdi:Peso ?peso .
            FILTER("""

    if name is not None:
        query += """str(?nombre) = '""" + name + """'"""
        first_filter = 1

    if brand is not None:
        if first_filter == 1:
            query += """ && """
        else:
            first_filter = 1
        query += """str(?marca) = '""" + brand + """'"""

    if prod_type is not None:
        if first_filter == 1:
            query += """ && """
        else:
            first_filter = 1
        query += """str(?tipo) = '""" + prod_type + """'"""
    
    if first_filter == 1:
        query += """ && """
    query += """?precio >= """ + str(min_price) + """ &&
                ?precio <= """ + str(max_price) + """  )}
                order by asc(UCASE(str(?nombre)))"""
    
    graph_query = graph.query(query)
    result = Graph()
    result.bind('ECSDI', ECSDI)

    productos_encontrados = ECSDI['productos_encontrados' + mss_cnt]
    result.add((productos_encontrados, RDF.type, ECSDI.Productos_encontrados))

    product_count = 0
    for row in graph_query:
        name = row.nombre
        brand = row.marca
        prod_type = row.tipo
        price = row.precio
        weight = row.peso
        logger.debug(name, brand, prod_type, price)
        subject = row.producto
        product_count += 1
        result.add((subject, RDF.type, ECSDI.Producto))
        result.add((subject, ECSDI.Nombre, Literal(name, datatype=XSD.string)))
        result.add((subject, ECSDI.Marca, Literal(brand, datatype=XSD.string)))
        result.add((subject, ECSDI.Tipo, Literal(prod_type, datatype=XSD.string)))
        result.add((subject, ECSDI.Precio, Literal(price, datatype=XSD.float)))
        result.add((subject, ECSDI.Peso, Literal(weight, datatype=XSD.integer)))
        result.add((productos_encontrados, ECSDI.Contiene_producto, subject))
    return result

def recordNewOrder(gm):
    global mss_cnt

    ordersFile = open('../Data/orders')
    ordersGraph = Graph()
    ordersGraph.parse(ordersFile, format='turtle')

    gNewOrder = Graph()
    gNewOrder.bind('ECSDI', ECSDI)
    order = ECSDI['pedido' + mss_cnt]
    # There is only one order in a 'Procesar_Compra' message, 'for' only will do one loop
    for neworder in gm.subjects(RDF.type, ECSDI.Procesar_Compra):
        city = gm.value(subject=neworder, predicate=ECSDI.Direccion_Envio)
        priority = gm.value(subject=neworder, predicate=ECSDI.Prioridad_Entrega)
        gNewOrder.add((order, RDF.type, ECSDI.Pedido))
        gNewOrder.add((order, ECSDI.Ciudad_Destino, Literal(city, datatype=XSD.string)))
        gNewOrder.add((order, ECSDI.Prioridad_Entrega, Literal(priority, datatype=XSD.string)))
    
    for product in gm.subjects(RDF.type, ECSDI.Producto):
        name = gm.value(subject=product, predicate=ECSDI.Nombre)
        brand = gm.value(subject=product, predicate=ECSDI.Marca)
        prod_type = gm.value(subject=product, predicate=ECSDI.Tipo)
        price = gm.value(subject=product, predicate=ECSDI.Precio)
        weight = gm.value(subject=product, predicate=ECSDI.Peso)
        gNewOrder.add((product, RDF.type, ECSDI.Producto))
        gNewOrder.add((product, ECSDI.Nombre, Literal(name, datatype=XSD.string)))
        gNewOrder.add((product, ECSDI.Marca, Literal(brand, datatype=XSD.string)))
        gNewOrder.add((product, ECSDI.Tipo, Literal(prod_type, datatype=XSD.string)))
        gNewOrder.add((product, ECSDI.Precio, Literal(price, datatype=XSD.float)))
        gNewOrder.add((product, ECSDI.Peso, Literal(weight, datatype=XSD.integer)))
        gNewOrder.add((order, ECSDI.Productos_Pedido, product))
    
    for s, p, o in gNewOrder:
        ordersGraph.add((s, p, o))
    
    ordersGraph.serialize(destination='../data/orders', format='turtle')

    return gNewOrder

def assignToLogisticCenter(gr):
    global mss_cnt

    content = ECSDI['enviar_pedido' + mss_cnt]
    gr.add((content, RDF.type, ECSDI.Enviar_Pedido))

    # There is only one order. To find it, first we obtain a list with this order (subjectsFound) and later we find the order inside the list.
    subjectsFound = gr.subjects(predicate=RDF.type, object=ECSDI.Pedido)
    for s in subjectsFound:
        order = s
        
    gr.add((content, ECSDI.Pedido_A_Enviar, order))

    logistic = get_agent_info(ECSDI.Centro_Logistico, DirectoryAgent, SalesProcessorAgent, mss_cnt)

    gr = send_message(
        build_message(gr, perf=ACL.request, sender=SalesProcessorAgent.uri, receiver=logistic.uri, msgcnt=mss_cnt, content=content),
        logistic.address
    )

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