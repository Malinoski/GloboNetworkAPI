# -*- coding:utf-8 -*-

# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ast
import json
import logging
import operator
import re
from networkapi.equipamento.models import Equipamento, EquipamentoRoteiro
from networkapi.interface.models import Interface, InterfaceNotFoundError
from networkapi.ip.models import Ip, IpEquipamento
from networkapi.rack.models import Rack, Datacenter, DatacenterRooms, RackConfigError
from networkapi.system import exceptions as var_exceptions
from networkapi.system.facade import get_value as get_variable
from networkapi.api_rack import exceptions, serializers, autoprovision
from django.core.exceptions import ObjectDoesNotExist
from django.forms.models import model_to_dict
from netaddr import IPNetwork
from rest_framework.decorators import api_view
from rest_framework import status
from rest_framework.response import Response


log = logging.getLogger(__name__)

def save_dc(dc_dict):

    dc = Datacenter()

    dc.dcname = dc_dict.get('dcname')
    dc.address = dc_dict.get('address')

    dc.save_dc()
    return dc


def save_dcrooms(dcrooms_dict):

    dcrooms = DatacenterRooms()

    dcrooms.dc = Datacenter().get_dc(idt=dcrooms_dict.get('dc'))
    dcrooms.name = dcrooms_dict.get('name')
    dcrooms.racks = dcrooms_dict.get('racks')
    dcrooms.spines = dcrooms_dict.get('spines')
    dcrooms.leafs = dcrooms_dict.get('leafs')
    dcrooms.config = dcrooms_dict.get('config')

    dcrooms.save_dcrooms()
    return dcrooms


def edit_dcrooms(dcroom_id, dcrooms_dict):

    dcrooms = DatacenterRooms().get_dcrooms(idt=dcroom_id)

    if dcrooms_dict.get('name'):
        dcrooms.name = dcrooms_dict.get('name')
    if dcrooms_dict.get('racks'):
        dcrooms.racks = dcrooms_dict.get('racks')
    if dcrooms_dict.get('spines'):
        dcrooms.spines = dcrooms_dict.get('spines')
    if dcrooms_dict.get('leafs'):
        dcrooms.leafs = dcrooms_dict.get('leafs')
    if dcrooms_dict.get('config'):
        dcrooms.config = dcrooms_dict.get('config')

    dcrooms.save_dcrooms()
    return dcrooms


def save_rack_dc(rack_dict):

    rack = Rack()

    rack.nome = rack_dict.get('name')
    rack.numero = rack_dict.get('number')
    rack.mac_sw1 = rack_dict.get('mac_sw1')
    rack.mac_sw2 = rack_dict.get('mac_sw2')
    rack.mac_ilo = rack_dict.get('mac_ilo')
    rack.id_sw1 = Equipamento().get_by_pk(rack_dict.get('id_sw1'))
    rack.id_sw2 = Equipamento().get_by_pk(rack_dict.get('id_sw2'))
    rack.id_sw3 = Equipamento().get_by_pk(rack_dict.get('id_ilo'))
    rack.dcroom = DatacenterRooms().get_dcrooms(idt=rack_dict.get('dcroom')) if rack_dict.get('dcroom') else None

    if not rack.nome:
        raise exceptions.InvalidInputException("O nome do Rack não foi informado.")

    rack.save_rack()
    return rack


def buscar_roteiro(id_sw, tipo):

    roteiros = EquipamentoRoteiro.search(None, id_sw)
    for rot in roteiros:
        if (rot.roteiro.tipo_roteiro.tipo==tipo):
            roteiro_eq = rot.roteiro.roteiro
    roteiro_eq = roteiro_eq.lower()
    if not '.txt' in roteiro_eq:
        roteiro_eq=roteiro_eq+".txt"

    return roteiro_eq


def buscar_ip(id_sw):
    '''Retuns switch IP that is registered in a management environment
    '''

    ip_sw=None

    ips_equip = IpEquipamento().list_by_equip(id_sw)
    regexp = re.compile(r'GERENCIA')

    mgnt_ip = None
    for ip_equip in ips_equip:
        ip_sw = ip_equip.ip
        if not ip_sw == None:
            if regexp.search(ip_sw.networkipv4.vlan.ambiente.ambiente_logico.nome) is not None:
                return str(ip_sw.oct1) + '.' + str(ip_sw.oct2) + '.' + str(ip_sw.oct3) + '.' + str(ip_sw.oct4)

    return ""


def gerar_arquivo_config(ids):

    for id in ids:
        rack = Rack().get_rack(idt=id)
        equips = list()
        lf1 = dict()
        lf2 = dict()
        oob = dict()

        #Equipamentos
        num_rack = rack.numero
        try:
            nome_rack = rack.nome.upper()
            lf1["sw"] = 1
            lf1["id"] = rack.id_sw1.id
            lf1["nome"] = rack.id_sw1.nome
            lf1["mac"] = rack.mac_sw1
            lf1["marca"] = rack.id_sw1.modelo.marca.nome
            lf1["modelo"] = rack.id_sw1.modelo.nome
            equips.append(lf1)
            lf2["sw"] = 2
            lf2["id"] = rack.id_sw2.id
            lf2["nome"] = rack.id_sw2.nome
            lf2["mac"] = rack.mac_sw2
            lf2["marca"] = rack.id_sw2.modelo.marca.nome
            lf2["modelo"] = rack.id_sw2.modelo.nome
            equips.append(lf2)
            oob["sw"] = 3
            oob["id"] = rack.id_ilo.id
            oob["nome"] = rack.id_ilo.nome
            oob["mac"] = rack.mac_ilo
            oob["marca"] = rack.id_ilo.modelo.marca.nome
            oob["modelo"] = rack.id_ilo.modelo.nome
            equips.append(oob)
            dcroom = rack.dcroom
            dcname = rack.dcroom.dc.dcname
        except:
            raise Exception("Erro: Informações incompletas. Verifique o cadastro do Datacenter, da Sala e do Rack")


        dcsigla = "".join([c[0] for c in dcname.split(" ")]) if len(dcname.split(" ")) >= 2 else dcname[:3]
        radical = "-" + dcsigla + "-" + nome_rack + "-"
        prefixspn = "SPN"
        prefixlf = "LF-"
        prefixoob = "OOB"

        # Interface e Roteiro
        for equip in equips:
            try:
                interfaces = Interface.search(equip.get("id"))
                equip["interfaces"] = list()
                for interface in interfaces:
                    dic = dict()
                    try:
                        sw = interface.get_switch_and_router_interface_from_host_interface(None)
                        if  (sw.equipamento.nome[:3] in [prefixlf, prefixoob, prefixspn]):
                            dic["nome"] = sw.equipamento.nome
                            dic["id"] = sw.equipamento.id
                            dic["ip_mngt"] = buscar_ip(sw.equipamento.id)
                            dic["interface"] = sw.interface
                            dic["eq_interface"] = interface.interface
                            dic["roteiro"] = buscar_roteiro(sw.equipamento.id, "CONFIGURACAO")
                            equip["interfaces"].append(dic)
                    except:
                        pass
            except:
                raise Exception("Erro ao buscar o roteiro de configuracao ou as interfaces associadas ao equipamento: "
                                "%s." % equip.get("nome"))
            try:
                equip["roteiro"] = buscar_roteiro(equip.get("id"), "CONFIGURACAO")
                equip["ip_mngt"] = buscar_ip(equip.get("id"))
            except:
                raise Exception("Erro ao buscar os roteiros do equipamento: %s" % equip.get("nome"))

        try:
            NETWORKAPI_USE_FOREMAN = int(get_variable("use_foreman"))
            NETWORKAPI_FOREMAN_URL = get_variable("foreman_url")
            NETWORKAPI_FOREMAN_USERNAME = get_variable("foreman_username")
            NETWORKAPI_FOREMAN_PASSWORD = get_variable("foreman_password")
            FOREMAN_HOSTS_ENVIRONMENT_ID = get_variable("foreman_hosts_environment_id")
        except ObjectDoesNotExist:
            raise var_exceptions.VariableDoesNotExistException("Erro buscando as variáveis relativas ao Foreman.")

        # begin - Create Foreman entries for rack switches
        if NETWORKAPI_USE_FOREMAN:
            foreman = Foreman(NETWORKAPI_FOREMAN_URL, (NETWORKAPI_FOREMAN_USERNAME, NETWORKAPI_FOREMAN_PASSWORD),
                              api_version=2)

            # for each switch, check the switch ip against foreman know networks, finds foreman hostgroup
            # based on model and brand and inserts the host in foreman
            # if host already exists, delete and recreate with new information
            for equip in equips:
                #Get all foremand subnets and compare with the IP address of the switches until find it
                switch_nome = equip.get("nome")
                switch_modelo = equip.get("modelo")
                switch_marca = equip.get("marca")
                mac = equip.get("mac")
                ip = equip.get("ip_mngt")

                if mac == None:
                    raise Exception("Could not create entry for %s. There is no mac address." % (switch_nome))

                if ip == None:
                    raise RackConfigError(None, rack.nome,
                                          ("Could not create entry for %s. There is no management IP." % (switch_nome)))

                switch_cadastrado = 0
                for subnet in foreman.subnets.index()['results']:
                    network = IPNetwork(ip+'/'+subnet['mask']).network
                    # check if switches ip network is the same as subnet['subnet']['network'] e subnet['subnet']['mask']
                    if network.__str__() == subnet['network']:
                        subnet_id = subnet['id']
                        hosts = foreman.hosts.index(search=switch_nome)['results']
                        if len(hosts) == 1:
                            foreman.hosts.destroy(id=hosts[0]['id'])
                        elif len(hosts) > 1:
                            raise Exception("Could not create entry for %s. There are multiple "
                                                                    "entries with the same name." % (switch_nome))

                        # Lookup foreman hostgroup
                        # By definition, hostgroup should be Marca+"_"+Modelo
                        hostgroup_name = switch_marca+"_"+switch_modelo
                        hostgroups = foreman.hostgroups.index(search=hostgroup_name)
                        if len(hostgroups['results']) == 0:
                            raise Exception("Could not create entry for %s.Could not find hostgroup %s in foreman." %
                                                  (switch_nome, hostgroup_name))
                        elif len(hostgroups['results'])>1:
                            raise Exception("Could not create entry for %s. Multiple hostgroups %s found in Foreman."
                                            %(switch_nome,hostgroup_name))
                        else:
                            hostgroup_id = hostgroups['results'][0]['id']

                        host = foreman.hosts.create(host={'name': switch_nome, 'ip': ip, 'mac': mac,
                                                          'environment_id': FOREMAN_HOSTS_ENVIRONMENT_ID,
                                                          'hostgroup_id': hostgroup_id, 'subnet_id': subnet_id,
                                                          'build': 'true', 'overwrite': 'true'})
                        switch_cadastrado = 1

                if not switch_cadastrado:
                    raise Exception("Unknown error. Could not create entry for %s in foreman." % (switch_nome))

        # end - Create Foreman entries for rack switches

        log.info(str(equips))
        var1 = autoprovision.autoprovision_splf(rack, equips)
        var2 = autoprovision.autoprovision_coreoob(rack, equips)

        if var1 and var2:
            return True
        return False


def dic_vlan_core(variablestochangecore, rack, name_core, name_rack):
    """
    variablestochangecore: list
    rack: Numero do Rack
    name_core: Nome do Core
    name_rack: Nome do rack
    """

    core = int(name_core.split("-")[2])

    try:
        # valor base para as vlans e portchannels
        BASE_SO = int(get_variable("base_so"))
        # rede para conectar cores aos racks
        SO_OOB_NETipv4 = IPNetwork(get_variable("net_core"))
        # Vlan para cadastrar
        vlan_so_name = get_variable("vlan_so_name")
    except ObjectDoesNotExist, exception:
        log.error(exception)
        raise var_exceptions.VariableDoesNotExistException("Erro buscando a variável BASE_SO ou SO_OOB_NETipv4.")

    variablestochangecore["VLAN_SO"] = str(BASE_SO+rack)
    variablestochangecore["VLAN_NAME"] = vlan_so_name+name_rack
    variablestochangecore["VLAN_NUM"] = str(BASE_SO+rack)

    # Rede para cadastrar
    subSO_OOB_NETipv4 = list(SO_OOB_NETipv4.subnet(25))
    variablestochangecore["REDE_IP"] = str(subSO_OOB_NETipv4[rack]).split("/")[0]
    variablestochangecore["REDE_MASK"] = str(subSO_OOB_NETipv4[rack].prefixlen)
    variablestochangecore["NETMASK"] = str(subSO_OOB_NETipv4[rack].netmask)
    variablestochangecore["BROADCAST"] = str(subSO_OOB_NETipv4[rack].broadcast)

    # cadastro ip
    ip = 124 + core
    variablestochangecore["EQUIP_NAME"] = name_core
    variablestochangecore["IPCORE"] = str(subSO_OOB_NETipv4[rack][ip])

    # ja cadastrado
    variablestochangecore["IPHSRP"] = str(subSO_OOB_NETipv4[rack][1])
    variablestochangecore["NUM_CHANNEL"] = str(BASE_SO+rack)

    return variablestochangecore


def dic_lf_spn(rack):

    CIDREBGP = dict()
    CIDRBE = dict()
    ########
    VLANBELEAF = dict()
    VLANFELEAF = dict()
    VLANBORDALEAF = dict()
    VLANBORDACACHOSLEAF = dict()
    ########
    VLANBELEAF[rack] = list()
    VLANFELEAF[rack] = list()
    VLANBORDALEAF[rack] = list()
    VLANBORDACACHOSLEAF[rack] = list()

    ipv4_spn1 = dict()
    ipv4_spn2 = dict()
    ipv4_spn3 = dict()
    ipv4_spn4 = dict()
    redev6_spn1 = dict()
    redev6_spn2 = dict()
    redev6_spn3 = dict()
    redev6_spn4 = dict()

    try:
        BASE_RACK = int(get_variable("base_rack"))
        VLANBE = int(get_variable("vlanbe"))
        VLANFE = int(get_variable("vlanfe"))
        VLANBORDA = int(get_variable("vlanborda"))
        VLANBORDACACHOS = int(get_variable("vlanbordacachos"))
        VLANBETORxTOR = int(get_variable("vlanbetorxtor"))
        # CIDR sala 01 => 10.128.0.0/12
        CIDRBE[0] = IPNetwork(get_variable("cidr_sl01"))
        CIDREBGP[0] = IPNetwork(get_variable("cidr_bgp"))
    except ObjectDoesNotExist, exception:
        log.error(exception)
        raise var_exceptions.VariableDoesNotExistException("Erro buscando a variável BASE_RACK ou VLAN<BE,FE,BORDA,"
                                                           "CACHOS,TORxTOR> ou CIDR<BE,EBGP>.")

    SPINE1ipv4 = IPNetwork(get_variable("net_spn01"))
    SPINE2ipv4 = IPNetwork(get_variable("net_spn02"))
    SPINE3ipv4 = IPNetwork(get_variable("net_spn03"))
    SPINE4ipv4 = IPNetwork(get_variable("net_spn04"))
    # REDE subSPINE1ipv4[rack]
    subSPINE1ipv4 = list(SPINE1ipv4.subnet(31))
    subSPINE2ipv4 = list(SPINE2ipv4.subnet(31))
    subSPINE3ipv4 = list(SPINE3ipv4.subnet(31))
    subSPINE4ipv4 = list(SPINE4ipv4.subnet(31))

    SPINE1ipv6 = IPNetwork(get_variable("net_spn01_v6"))
    SPINE2ipv6 = IPNetwork(get_variable("net_spn02_v6"))
    SPINE3ipv6 = IPNetwork(get_variable("net_spn03_v6"))
    SPINE4ipv6 = IPNetwork(get_variable("net_spn04_v6"))
    subSPINE1ipv6 = list(SPINE1ipv6.subnet(127))
    subSPINE2ipv6 = list(SPINE2ipv6.subnet(127))
    subSPINE3ipv6 = list(SPINE3ipv6.subnet(127))
    subSPINE4ipv6 = list(SPINE4ipv6.subnet(127))

    # Vlans BE RANGE
    VLANBELEAF[rack].append(VLANBE+rack)
    # rede subSPINE1ipv4[rack]
    VLANBELEAF[rack].append(VLANBE+rack+BASE_RACK)
    VLANBELEAF[rack].append(VLANBE+rack+2*BASE_RACK)
    VLANBELEAF[rack].append(VLANBE+rack+3*BASE_RACK)
    # Vlans FE RANGE
    VLANFELEAF[rack].append(VLANFE+rack)
    VLANFELEAF[rack].append(VLANFE+rack+BASE_RACK)
    VLANFELEAF[rack].append(VLANFE+rack+2*BASE_RACK)
    VLANFELEAF[rack].append(VLANFE+rack+3*BASE_RACK)
    # Vlans BORDA RANGE
    VLANBORDALEAF[rack].append(VLANBORDA+rack)
    VLANBORDALEAF[rack].append(VLANBORDA+rack+BASE_RACK)
    VLANBORDALEAF[rack].append(VLANBORDA+rack+2*BASE_RACK)
    VLANBORDALEAF[rack].append(VLANBORDA+rack+3*BASE_RACK)
    # Vlans BORDACACHOS RANGE
    VLANBORDACACHOSLEAF[rack].append(VLANBORDACACHOS+rack)
    VLANBORDACACHOSLEAF[rack].append(VLANBORDACACHOS+rack+BASE_RACK)
    VLANBORDACACHOSLEAF[rack].append(VLANBORDACACHOS+rack+2*BASE_RACK)
    VLANBORDACACHOSLEAF[rack].append(VLANBORDACACHOS+rack+3*BASE_RACK)

    # ########## BD ############
    vlans = dict()
    vlans['VLANBELEAF'] = VLANBELEAF
    vlans['VLANFELEAF'] = VLANFELEAF
    vlans['VLANBORDALEAF'] = VLANBORDALEAF
    vlans['VLANBORDACACHOSLEAF'] = VLANBORDACACHOSLEAF
    vlans['BE'] = [VLANBE, VLANFE]
    vlans['FE'] = [VLANFE, VLANBORDA]
    vlans['BORDA'] = [VLANBORDA, VLANBORDACACHOS]
    vlans['BORDACACHOS'] = [VLANBORDACACHOS, VLANBETORxTOR]

    ipv4_spn1['REDE_IP'] = str(subSPINE1ipv4[rack].ip)
    ipv4_spn1['REDE_MASK'] = subSPINE1ipv4[rack].prefixlen
    ipv4_spn1['NETMASK'] = str(subSPINE1ipv4[rack].netmask)
    ipv4_spn1['BROADCAST'] = str(subSPINE1ipv4[rack].broadcast)

    ipv4_spn2['REDE_IP'] = str(subSPINE2ipv4[rack].ip)
    ipv4_spn2['REDE_MASK'] = subSPINE2ipv4[rack].prefixlen
    ipv4_spn2['NETMASK'] = str(subSPINE2ipv4[rack].netmask)
    ipv4_spn2['BROADCAST'] = str(subSPINE2ipv4[rack].broadcast)

    ipv4_spn3['REDE_IP'] = str(subSPINE3ipv4[rack].ip)
    ipv4_spn3['REDE_MASK'] = subSPINE3ipv4[rack].prefixlen
    ipv4_spn3['NETMASK'] = str(subSPINE3ipv4[rack].netmask)
    ipv4_spn3['BROADCAST'] = str(subSPINE3ipv4[rack].broadcast)

    ipv4_spn4['REDE_IP'] = str(subSPINE4ipv4[rack].ip)
    ipv4_spn4['REDE_MASK'] = subSPINE4ipv4[rack].prefixlen
    ipv4_spn4['NETMASK'] = str(subSPINE4ipv4[rack].netmask)
    ipv4_spn4['BROADCAST'] = str(subSPINE4ipv4[rack].broadcast)

    redev6_spn1['REDE_IP'] = str(subSPINE1ipv6[rack].ip)
    redev6_spn1['REDE_MASK'] = subSPINE1ipv6[rack].prefixlen
    redev6_spn1['NETMASK'] = str(subSPINE1ipv6[rack].netmask)
    redev6_spn1['BROADCAST'] = str(subSPINE1ipv6[rack].broadcast)

    redev6_spn2['REDE_IP'] = str(subSPINE2ipv6[rack].ip)
    redev6_spn2['REDE_MASK'] = subSPINE2ipv6[rack].prefixlen
    redev6_spn2['NETMASK'] = str(subSPINE2ipv6[rack].netmask)
    redev6_spn2['BROADCAST'] = str(subSPINE2ipv6[rack].broadcast)

    redev6_spn3['REDE_IP'] = str(subSPINE3ipv6[rack].ip)
    redev6_spn3['REDE_MASK'] = subSPINE3ipv6[rack].prefixlen
    redev6_spn3['NETMASK'] = str(subSPINE3ipv6[rack].netmask)
    redev6_spn3['BROADCAST'] = str(subSPINE3ipv6[rack].broadcast)

    redev6_spn4['REDE_IP'] = str(subSPINE4ipv6[rack].ip)
    redev6_spn4['REDE_MASK'] = subSPINE4ipv6[rack].prefixlen
    redev6_spn4['NETMASK'] = str(subSPINE4ipv6[rack].netmask)
    redev6_spn4['BROADCAST'] = str(subSPINE4ipv6[rack].broadcast)

    redes = dict()
    redes['SPINE1ipv4'] = str(SPINE1ipv4)
    redes['SPINE1ipv4_net'] = ipv4_spn1
    redes['SPINE2ipv4'] = str(SPINE2ipv4)
    redes['SPINE2ipv4_net'] = ipv4_spn2
    redes['SPINE3ipv4'] = str(SPINE3ipv4)
    redes['SPINE3ipv4_net'] = ipv4_spn3
    redes['SPINE4ipv4'] = str(SPINE4ipv4)
    redes['SPINE4ipv4_net'] = ipv4_spn4

    ipv6 = dict()
    ipv6['SPINE1ipv6'] = str(SPINE1ipv6)
    ipv6['SPINE1ipv6_net'] = redev6_spn1
    ipv6['SPINE2ipv6'] = str(SPINE2ipv6)
    ipv6['SPINE2ipv6_net'] = redev6_spn2
    ipv6['SPINE3ipv6'] = str(SPINE3ipv6)
    ipv6['SPINE3ipv6_net'] = redev6_spn3
    ipv6['SPINE4ipv6'] = str(SPINE4ipv6)
    ipv6['SPINE4ipv6_net'] = redev6_spn4

    return vlans, redes, ipv6


def dic_pods(rack):

    subnetsRackBEipv4 = dict()
    subnetsRackBEipv4[rack] = list()

    PODSBEipv4 = dict()
    redesPODSBEipv4 = dict()
    PODSBEFEipv4 = dict()
    redesPODSBEFEipv4 = dict()
    PODSBEBOipv4 = dict()
    redesPODSBEBOipv4 = dict()
    PODSBECAipv4 = dict()
    redesPODSBECAipv4 = dict()

    PODSBEipv4[rack] = list()
    redesPODSBEipv4[rack] = list()
    PODSBEFEipv4[rack] = list()
    redesPODSBEFEipv4[rack] = list()
    PODSBEBOipv4[rack] = list()
    redesPODSBEBOipv4[rack] = list()
    PODSBECAipv4[rack] = list()
    redesPODSBECAipv4[rack] = list()

    PODSBEipv6 = dict()
    redesPODSBEipv6 = dict()
    PODSBEFEipv6 = dict()
    redesPODSBEFEipv6 = dict()
    PODSBEBOipv6 = dict()
    redesPODSBEBOipv6 = dict()
    PODSBECAipv6 = dict()
    redesPODSBECAipv6 = dict()
    subnetsRackBEipv6 = dict()

    PODSBEipv6[rack] = list()
    redesPODSBEipv6[rack] = list()
    PODSBEFEipv6[rack] = list()
    redesPODSBEFEipv6[rack] = list()
    PODSBEBOipv6[rack] = list()
    redesPODSBEBOipv6[rack] = list()
    PODSBECAipv6[rack] = list()
    redesPODSBECAipv6[rack] = list()
    subnetsRackBEipv6[rack] = list()

    try:
        # CIDR sala 01 => 10.128.0.0/12
        CIDRBEipv4 = IPNetwork(get_variable("cidr_be_v4"))
        CIDRBEipv6 = IPNetwork(get_variable("cidr_be_v6"))
    except ObjectDoesNotExist, exception:
        log.error(exception)
        raise var_exceptions.VariableDoesNotExistException("Erro buscando a variável CIDR<BEv4,BEv6>.")

    #          ::::::: SUBNETING FOR RACK NETWORKS - /19 :::::::

    # Redes p/ rack => 10.128.0.0/19, 10.128.32.0/19 , ... ,10.143.224.0/19
    subnetsRackBEipv4[rack] = splitnetworkbyrack(CIDRBEipv4, 19, rack)
    subnetsRackBEipv6[rack] = splitnetworkbyrack(CIDRBEipv6, 55, rack)

    # PODS BE => /20
    subnetteste = subnetsRackBEipv4[rack]
    subnetteste_ipv6 = subnetsRackBEipv6[rack]

    PODSBEipv4[rack] = splitnetworkbyrack(subnetteste, 20, 0)
    PODSBEipv6[rack] = splitnetworkbyrack(subnetteste_ipv6, 57, 0)
    # => 256 redes /28
    # Vlan 2 a 129
    redesPODSBEipv4[rack] = list(PODSBEipv4[rack].subnet(28))
    redesPODSBEipv6[rack] = list(PODSBEipv6[rack].subnet(64))
    # PODS BEFE => 10.128.16.0/21
    PODSBEFEipv4[rack] = splitnetworkbyrack(splitnetworkbyrack(subnetteste, 20, 1), 21, 0)
    PODSBEFEipv6[rack] = splitnetworkbyrack(subnetteste_ipv6, 57, 1)
    # => 128 redes /28
    #  Vlan 130 a 193
    redesPODSBEFEipv4[rack] = list(PODSBEFEipv4[rack].subnet(28))
    redesPODSBEFEipv6[rack] = list(PODSBEFEipv6[rack].subnet(64))
    # PODS BEBO => 10.128.24.0/22
    PODSBEBOipv4[rack] = splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(subnetteste, 20, 1), 21, 1), 22, 0)
    PODSBEBOipv6[rack] = splitnetworkbyrack(subnetteste_ipv6, 57, 2)
    # => 64 redes /28
    # Vlan 194 a 257
    redesPODSBEBOipv4[rack] = list(PODSBEBOipv4[rack].subnet(28))
    redesPODSBEBOipv6[rack] = list(PODSBEBOipv6[rack].subnet(64))
    # PODS BECA => 10.128.28.0/23
    PODSBECAipv4[rack] = splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(subnetteste, 20, 1),
                                                                                  21, 1), 22, 1), 23, 0)
    PODSBECAipv6[rack] = splitnetworkbyrack(splitnetworkbyrack(subnetteste_ipv6, 57, 3), 58, 0)
    # => 32 redes /28
    # Vlan 258 a 289
    redesPODSBECAipv4[rack] = list(PODSBECAipv4[rack].subnet(28))
    redesPODSBECAipv6[rack] = list(PODSBECAipv6[rack].subnet(64))

    redes = dict()
    ipv6 = dict()
    redes['BE_VLAN_MIN'] = int(get_variable("be_vlan_min"))
    redes['BE_VLAN_MAX'] = int(get_variable("be_vlan_max"))
    redes['BE_PREFIX'] = str(redesPODSBEipv4[rack][0].prefixlen)
    redes['BE_REDE'] = str(PODSBEipv4[rack])
    ipv6['BE_PREFIX'] = str(redesPODSBEipv6[rack][0].prefixlen)
    ipv6['BE_REDE'] = str(PODSBEipv6[rack])

    redes['BEFE_VLAN_MIN'] = int(get_variable("befe_vlan_min"))
    redes['BEFE_VLAN_MAX'] = int(get_variable("befe_vlan_max"))
    redes['BEFE_PREFIX'] = str(redesPODSBEFEipv4[rack][0].prefixlen)
    redes['BEFE_REDE'] = str(PODSBEFEipv4[rack])
    ipv6['BEFE_PREFIX'] = str(redesPODSBEFEipv6[rack][0].prefixlen)
    ipv6['BEFE_REDE'] = str(PODSBEFEipv6[rack])

    redes['BEBORDA_VLAN_MIN'] = int(get_variable("beborda_vlan_min"))
    redes['BEBORDA_VLAN_MAX'] = int(get_variable("beborda_vlan_max"))
    redes['BEBORDA_PREFIX'] = str(redesPODSBEBOipv4[rack][0].prefixlen)
    redes['BEBORDA_REDE'] = str(PODSBEBOipv4[rack])
    ipv6['BEBORDA_PREFIX'] = str(redesPODSBEBOipv6[rack][0].prefixlen)
    ipv6['BEBORDA_REDE'] = str(PODSBEBOipv6[rack])

    redes['BECACHOS_VLAN_MIN'] = int(get_variable("becachos_vlan_min"))
    redes['BECACHOS_VLAN_MAX'] = int(get_variable("becachos_vlan_max"))
    redes['BECACHOS_PREFIX'] = str(redesPODSBECAipv4[rack][0].prefixlen)
    redes['BECACHOS_REDE'] = str(PODSBECAipv4[rack])
    ipv6['BECACHOS_PREFIX'] = str(redesPODSBECAipv6[rack][0].prefixlen)
    ipv6['BECACHOS_REDE'] = str(PODSBECAipv6[rack])

    return redes, ipv6


def dic_hosts_cloud(rack):

    subnetsRackBEipv4 = dict()
    subnetsRackBEipv4[rack] = list()
    redesHostsipv4 = dict()
    redesHostsipv4[rack] = list()
    redeHostsBEipv4 = dict()
    redeHostsBEipv4[rack] = list()
    redeHostsFEipv4 = dict()
    redeHostsFEipv4[rack] = list()
    redeHostsBOipv4 = dict()
    redeHostsBOipv4[rack] = list()
    redeHostsCAipv4 = dict()
    redeHostsCAipv4[rack] = list()
    redeHostsFILERipv4 = dict()
    redeHostsFILERipv4[rack] = list()

    subnetsRackBEipv6 = dict()
    subnetsRackBEipv6[rack] = list()
    redesHostsipv6 = dict()
    redesHostsipv6[rack] = list()
    redeHostsBEipv6 = dict()
    redeHostsBEipv6[rack] = list()
    redeHostsFEipv6 = dict()
    redeHostsFEipv6[rack] = list()
    redeHostsBOipv6 = dict()
    redeHostsBOipv6[rack] = list()
    redeHostsCAipv6 = dict()
    redeHostsCAipv6[rack] = list()
    redeHostsFILERipv6 = dict()
    redeHostsFILERipv6[rack] = list()

    hosts = dict()
    BE = dict()
    FE = dict()
    BO = dict()
    CA = dict()
    FILER = dict()
    ipv6 = dict()
    BE_ipv6 = dict()
    FE_ipv6 = dict()
    BO_ipv6 = dict()
    CA_ipv6 = dict()
    FILER_ipv6 = dict()

    try:
        # CIDR sala 01 => 10.128.0.0/12
        CIDRBEipv4 = IPNetwork(get_variable("cidr_be_v4"))
        CIDRBEipv6 = IPNetwork(get_variable("cidr_be_v6"))
        hosts['VLAN_MNGT_BE'] = int(get_variable("vlan_mngt_be"))
        hosts['VLAN_MNGT_FE'] = int(get_variable("vlan_mngt_fe"))
        hosts['VLAN_MNGT_BO'] = int(get_variable("vlan_mngt_bo"))
        hosts['VLAN_MNGT_CA'] = int(get_variable("vlan_mngt_ca"))
        hosts['VLAN_MNGT_FILER'] = int(get_variable("vlan_mngt_filer"))
    except ObjectDoesNotExist, exception:
        log.error(exception)
        raise var_exceptions.VariableDoesNotExistException("Erro buscando a variável VLAN_MNGT<BE,FE,BO,CA,FILER> ou "
                                                           "CIDR<BEv4,BEv6>.")

    subnetsRackBEipv4[rack] = splitnetworkbyrack(CIDRBEipv4, 19, rack)  # 10.128.32.0/19
    subnetteste = subnetsRackBEipv4[rack]  # 10.128.32.0/19

    subnetsRackBEipv6[rack] = splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(CIDRBEipv6, 55, rack), 57, 3),
                                                 58, 1)
    subnetteste_ipv6 = splitnetworkbyrack(subnetsRackBEipv6[rack], 61, 7)

    # VLANS CLoud
    # ambiente BE - MNGT_NETWORK - RACK_AAXX
    # 10.128.30.0/23
    # vlans MNGT_BE/FE/BO/CA/FILER
    # PODS BE => /20
    # Hosts => 10.128.30.0/23
    redesHostsipv4[rack] = splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(
        subnetteste, 20, 1), 21, 1), 22, 1), 23, 1)
    redesHostsipv6[rack] = subnetteste_ipv6
    # Hosts BE => 10.128.30.0/24 => 256 endereços
    redeHostsBEipv4[rack] = splitnetworkbyrack(redesHostsipv4[rack], 24, 0)
    redeHostsBEipv6[rack] = splitnetworkbyrack(subnetteste_ipv6, 64, 3)
    # Hosts FE => 10.128.31.0/25 => 128 endereços
    redeHostsFEipv4[rack] = splitnetworkbyrack(splitnetworkbyrack(redesHostsipv4[rack], 24, 1), 25, 0)
    redeHostsFEipv6[rack] = splitnetworkbyrack(subnetteste_ipv6, 64, 4)
    # Hosts BO => 10.128.31.128/26 => 64 endereços
    redeHostsBOipv4[rack] = splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(redesHostsipv4[rack], 24, 1),
                                                                  25, 1), 26, 0)
    redeHostsBOipv6[rack] = splitnetworkbyrack(subnetteste_ipv6, 64, 5)
    # Hosts CA => 10.128.31.192/27 => 32 endereços
    redeHostsCAipv4[rack] = splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(
        redesHostsipv4[rack], 24, 1), 25, 1), 26, 1), 27, 0)
    redeHostsCAipv6[rack] = splitnetworkbyrack(subnetteste_ipv6, 64, 6)
    # Hosts FILER => 10.128.15.224/27 => 32 endereços
    redeHostsFILERipv4[rack] = splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(splitnetworkbyrack(
        redesHostsipv4[rack], 24, 1), 25, 1), 26, 1), 27, 1)
    redeHostsFILERipv6[rack] = splitnetworkbyrack(subnetteste_ipv6, 64, 7)

    hosts['PREFIX'] = str(redesHostsipv4[rack].prefixlen)
    hosts["REDE"] = str(redesHostsipv4[rack])
    BE['REDE_IP'] = str(redeHostsBEipv4[rack].ip)
    BE['REDE_MASK'] = redeHostsBEipv4[rack].prefixlen
    BE['NETMASK'] = str(redeHostsBEipv4[rack].netmask)
    BE['BROADCAST'] = str(redeHostsBEipv4[rack].broadcast)
    hosts['BE'] = BE
    FE['REDE_IP'] = str(redeHostsFEipv4[rack].ip)
    FE['REDE_MASK'] = redeHostsFEipv4[rack].prefixlen
    FE['NETMASK'] = str(redeHostsFEipv4[rack].netmask)
    FE['BROADCAST'] = str(redeHostsFEipv4[rack].broadcast)
    hosts['FE'] = FE
    BO['REDE_IP'] = str(redeHostsBOipv4[rack].ip)
    BO['REDE_MASK'] = redeHostsBOipv4[rack].prefixlen
    BO['NETMASK'] = str(redeHostsBOipv4[rack].netmask)
    BO['BROADCAST'] = str(redeHostsBOipv4[rack].broadcast)
    hosts['BO'] = BO
    CA['REDE_IP'] = str(redeHostsCAipv4[rack].ip)
    CA['REDE_MASK'] = redeHostsCAipv4[rack].prefixlen
    CA['NETMASK'] = str(redeHostsCAipv4[rack].netmask)
    CA['BROADCAST'] = str(redeHostsCAipv4[rack].broadcast)
    hosts['CA'] = CA
    FILER['REDE_IP'] = str(redeHostsFILERipv4[rack].ip)
    FILER['REDE_MASK'] = redeHostsFILERipv4[rack].prefixlen
    FILER['NETMASK'] = str(redeHostsFILERipv4[rack].netmask)
    FILER['BROADCAST'] = str(redeHostsFILERipv4[rack].broadcast)
    hosts['FILER'] = FILER

    ipv6['PREFIX'] = str(redesHostsipv6[rack].prefixlen)
    ipv6['REDE'] = str(redesHostsipv6[rack])
    BE_ipv6['REDE_IP'] = str(redeHostsBEipv6[rack].ip)
    BE_ipv6['REDE_MASK'] = redeHostsBEipv6[rack].prefixlen
    BE_ipv6['NETMASK'] = str(redeHostsBEipv6[rack].netmask)
    BE_ipv6['BROADCAST'] = str(redeHostsBEipv6[rack].broadcast)
    ipv6['BE'] = BE_ipv6
    FE_ipv6['REDE_IP'] = str(redeHostsFEipv6[rack].ip)
    FE_ipv6['REDE_MASK'] = redeHostsFEipv6[rack].prefixlen
    FE_ipv6['NETMASK'] = str(redeHostsFEipv6[rack].netmask)
    FE_ipv6['BROADCAST'] = str(redeHostsFEipv6[rack].broadcast)
    ipv6['FE'] = FE_ipv6
    BO_ipv6['REDE_IP'] = str(redeHostsBOipv6[rack].ip)
    BO_ipv6['REDE_MASK'] = redeHostsBOipv6[rack].prefixlen
    BO_ipv6['NETMASK'] = str(redeHostsBOipv6[rack].netmask)
    BO_ipv6['BROADCAST'] = str(redeHostsBOipv6[rack].broadcast)
    ipv6['BO'] = BO_ipv6
    CA_ipv6['REDE_IP'] = str(redeHostsCAipv6[rack].ip)
    CA_ipv6['REDE_MASK'] = redeHostsCAipv6[rack].prefixlen
    CA_ipv6['NETMASK'] = str(redeHostsCAipv6[rack].netmask)
    CA_ipv6['BROADCAST'] = str(redeHostsCAipv6[rack].broadcast)
    ipv6['CA'] = CA_ipv6
    FILER_ipv6['REDE_IP'] = str(redeHostsFILERipv6[rack].ip)
    FILER_ipv6['REDE_MASK'] = redeHostsFILERipv6[rack].prefixlen
    FILER_ipv6['NETMASK'] = str(redeHostsFILERipv6[rack].netmask)
    FILER_ipv6['BROADCAST'] = str(redeHostsFILERipv6[rack].broadcast)
    ipv6['FILER'] = FILER_ipv6
    return hosts, ipv6


def dic_fe_prod(rack):

    CIDRFEipv4 = dict()
    CIDRFEipv4[rack] = list()
    CIDRFEipv6 = dict()
    CIDRFEipv6[rack] = list()

    subnetsRackFEipv4 = dict()
    subnetsRackFEipv4[rack] = list()
    subnetsRackFEipv6 = dict()
    subnetsRackFEipv6[rack] = list()

    podsFEipv4 = dict()
    podsFEipv4[rack] = list()
    podsFEipv6 = dict()
    podsFEipv6[rack] = list()

    ipv6 = dict()
    ranges = dict()
    redes = dict()

    try:
        # CIDR sala 01 => 172.20.0.0/14
        # Sumário do rack => 172.20.0.0/21
        CIDRFEipv4[0] = IPNetwork(get_variable("cidr_fe_v4"))
        # CIDRFE[1] = IPNetwork('172.20.1.0/14')
        CIDRFEipv6[0] = IPNetwork(get_variable("cidr_fe_v6"))
    except ObjectDoesNotExist, exception:
        log.error(exception)
        raise var_exceptions.VariableDoesNotExistException("Erro buscando a variável VLAN_MNGT<BE,FE,BO,CA,FILER> ou "
                                                           "CIDR<FEv4,FEv6>.")

    # Sumário do rack => 172.20.0.0/21
    subnetsRackFEipv4[rack] = splitnetworkbyrack(CIDRFEipv4[0], 21, rack)
    subnetsRackFEipv6[rack] = splitnetworkbyrack(CIDRFEipv6[0], 57, rack)

    podsFEipv4[rack] = splitnetworkbyrack(subnetsRackFEipv4[rack], 28, 0)
    podsFEipv6[rack] = splitnetworkbyrack(subnetsRackFEipv6[rack], 64, 3)

    ranges['MAX'] = int(get_variable("fe_vlan_min"))
    ranges['MIN'] = int(get_variable("fe_vlan_max"))
    redes['PREFIX'] = podsFEipv4[rack].prefixlen
    redes['REDE'] = str(subnetsRackFEipv4[rack])

    ipv6['PREFIX'] = podsFEipv6[rack].prefixlen
    ipv6['REDE'] = str(subnetsRackFEipv6[rack])
    return redes, ranges, ipv6


# ################################################### old
def save_rack(rack_dict):

    rack = Rack()

    rack.nome = rack_dict.get('name')
    rack.numero = rack_dict.get('number')
    rack.mac_sw1 = rack_dict.get('sw1_mac')
    rack.mac_sw2 = rack_dict.get('sw2_mac')
    rack.mac_ilo = rack_dict.get('sw3_mac')
    id_sw1 = rack_dict.get('sw1_id')
    id_sw2 = rack_dict.get('sw2_id')
    id_sw3 = rack_dict.get('sw3_id')

    if not rack.nome:
        raise exceptions.InvalidInputException("O nome do Rack não foi informado.")
    if Rack.objects.filter(nome__iexact=rack.nome):
        raise exceptions.RackNameDuplicatedError()
    if Rack.objects.filter(numero__iexact=rack.numero):
        raise exceptions.RackNumberDuplicatedValueError()

    if not id_sw1:
        raise exceptions.InvalidInputException("O Leaf de id %s não existe." % id_sw1)
    if not id_sw2:
        raise exceptions.InvalidInputException("O Leaf de id %s não existe." % id_sw2)
    if not id_sw3:
        raise exceptions.InvalidInputException("O OOB de id %s não existe." % id_sw3)

    rack.id_sw1 = Equipamento.get_by_pk(int(id_sw1))
    rack.id_sw2 = Equipamento.get_by_pk(int(id_sw2))
    rack.id_ilo = Equipamento.get_by_pk(int(id_sw3))

    rack.save()
    return rack

def get_by_pk(user, idt):

    try:
        return Rack.objects.filter(id=idt).uniqueResult()
    except ObjectDoesNotExist, e:
        raise exceptions.RackNumberNotFoundError("Rack id %s nao foi encontrado" % (idt))
    except Exception, e:
        log.error(u'Failure to search the Rack.')
        raise exceptions.RackError("Failure to search the Rack. %s" % (e))

@api_view(['GET'])
def available_rack_number(request):

    log.info("Available Rack Number")

    data = dict()
    rack_anterior = 0

    for rack in Rack.objects.order_by('numero'):
        if rack.numero == rack_anterior:
            rack_anterior = rack_anterior + 1
        else:
            data['rack_number'] = rack_anterior if not rack_anterior > 119 else -1
            return Response(data, status=status.HTTP_200_OK)

    return Response(data, status=status.HTTP_200_OK)


