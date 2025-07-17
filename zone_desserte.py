# -*- coding: utf-8 -*-
"""
/***************************************************************************
 zonedesserte
                                 A QGIS plugin
 Extension visant à créer une zone de desserte avec un tampon
 ***************************************************************************/
"""

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (
    QgsProject, QgsFeature, QgsGeometry, QgsPointXY,
    QgsVectorLayer, QgsField, QgsProcessingFeatureSourceDefinition
)
from .resources import *
from .zone_desserte_dialog import zonedesserteDialog
import os.path
import processing

class zonedesserte:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(self.plugin_dir, 'i18n', f'zonedesserte_{locale}.qm')
        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)
        self.actions = []
        self.menu = self.tr('&Zone de desserte')
        self.first_start = True
        self.dlg = None
        self.manual_points_layer = None

    def tr(self, message):
        return QCoreApplication.translate('zonedesserte', message)

    def add_action(self, icon_path, text, callback,
                   enabled_flag=True, add_to_menu=True,
                   add_to_toolbar=True, status_tip=None,
                   whats_this=None, parent=None):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)
        if status_tip is not None:
            action.setStatusTip(status_tip)
        if whats_this is not None:
            action.setWhatsThis(whats_this)
        if add_to_toolbar:
            self.iface.addToolBarIcon(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)
        self.actions.append(action)
        return action

    def initGui(self):
        icon_path = ':/plugins/zone_desserte/icon.png'
        self.add_action(icon_path, self.tr('Zone de desserte'),
                        self.run, parent=self.iface.mainWindow())

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.tr('&Zone de desserte'), action)
            self.iface.removeToolBarIcon(action)
        if self.manual_points_layer:
            QgsProject.instance().removeMapLayer(self.manual_points_layer.id())

    def run(self):
        if self.first_start:
            self.first_start = False
            self.dlg = zonedesserteDialog()
            self.dlg.createPointsButton.clicked.connect(self.create_points)
            self.dlg.okButton.clicked.connect(self.process_service_area)
            self.populate_layer_comboboxes()
        else:
            self.populate_layer_comboboxes()

        self.dlg.progressBar.setValue(0)
        self.dlg.show()
        self.dlg.exec_()

    def populate_layer_comboboxes(self):
        self.dlg.lineLayerComboBox.clear()
        self.dlg.pointLayerComboBox.clear()

        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == QgsVectorLayer.VectorLayer:
                if layer.geometryType() == 1:
                    self.dlg.lineLayerComboBox.addItem(layer.name(), layer.id())
                elif layer.geometryType() == 0:
                    self.dlg.pointLayerComboBox.addItem(layer.name(), layer.id())

    def create_points(self):
        if self.manual_points_layer:
            QgsProject.instance().removeMapLayer(self.manual_points_layer.id())
            self.manual_points_layer = None

        line_index = self.dlg.lineLayerComboBox.currentIndex()
        if line_index == -1:
            QMessageBox.critical(self.dlg, "Erreur", "Aucune couche ligne sélectionnée")
            return

        line_layer_id = self.dlg.lineLayerComboBox.itemData(line_index)
        line_layer = QgsProject.instance().mapLayer(line_layer_id)
        if not line_layer:
            QMessageBox.critical(self.dlg, "Erreur", "Impossible de récupérer la couche ligne")
            return

        crs = line_layer.crs().authid()
        self.manual_points_layer = QgsVectorLayer(f"Point?crs={crs}", "Campagne d'écoute", "memory")
        prov = self.manual_points_layer.dataProvider()
        prov.addAttributes([QgsField("id", QVariant.Int)])
        self.manual_points_layer.updateFields()

        QgsProject.instance().addMapLayer(self.manual_points_layer)
        self.manual_points_layer.startEditing()

        self.iface.messageBar().pushMessage("Info", "Ajoutez vos points manuellement puis cliquez sur OK.", level=0, duration=5)

    def process_service_area(self):
        try:
            self.dlg.progressBar.setValue(0)

            # Récupération couche ligne
            line_index = self.dlg.lineLayerComboBox.currentIndex()
            if line_index == -1:
                QMessageBox.critical(self.dlg, "Erreur", "Aucune couche ligne sélectionnée")
                return
            line_layer_id = self.dlg.lineLayerComboBox.itemData(line_index)
            line_layer = QgsProject.instance().mapLayer(line_layer_id)
            if not line_layer:
                QMessageBox.critical(self.dlg, "Erreur", "Impossible de récupérer la couche ligne")
                return

            # Récupération couche points (manuels ou sélectionnés)
            if self.manual_points_layer:
                if self.manual_points_layer.isEditable():
                    self.manual_points_layer.commitChanges()
                start_points_layer = self.manual_points_layer
            else:
                point_index = self.dlg.pointLayerComboBox.currentIndex()
                if point_index == -1:
                    QMessageBox.critical(self.dlg, "Erreur", "Aucune couche point sélectionnée et aucun point manuel créé")
                    return
                point_layer_id = self.dlg.pointLayerComboBox.itemData(point_index)
                start_points_layer = QgsProject.instance().mapLayer(point_layer_id)
                if not start_points_layer:
                    QMessageBox.critical(self.dlg, "Erreur", "Impossible de récupérer la couche point sélectionnée")
                    return

            self.dlg.progressBar.setValue(10)

            # Densification ligne
            densify_params = {
                'INPUT': line_layer,
                'INTERVAL': 1,
                'OUTPUT': 'memory:'
            }
            densify_result = processing.run("native:densifygeometriesgivenaninterval", densify_params)
            densified_layer = densify_result['OUTPUT']
            densified_layer.setName("Lignes densifiées")
            QgsProject.instance().addMapLayer(densified_layer)

            self.dlg.progressBar.setValue(30)

            crs = densified_layer.crs().authid()
            zones_ecoute = []

            total_points = start_points_layer.featureCount()
            for idx, point_feat in enumerate(start_points_layer.getFeatures()):
                # Couche mémoire temporaire pour le point
                single_point_layer = QgsVectorLayer(f"Point?crs={crs}", f"point_tmp_{idx}", "memory")
                prov = single_point_layer.dataProvider()
                prov.addAttributes(start_points_layer.fields())
                single_point_layer.updateFields()
                prov.addFeatures([point_feat])
                single_point_layer.updateExtents()
                QgsProject.instance().addMapLayer(single_point_layer, addToLegend=False)

                # Trouver la ligne la plus proche pour le travel cost
                point_geom = point_feat.geometry().asPoint()
                nearest_line = None
                min_dist = None
                for line_feat in densified_layer.getFeatures():
                    dist = line_feat.geometry().distance(QgsGeometry.fromPointXY(QgsPointXY(point_geom)))
                    if min_dist is None or dist < min_dist:
                        min_dist = dist
                        nearest_line = line_feat
                if nearest_line is None:
                    QMessageBox.critical(self.dlg, "Erreur", f"Aucune ligne trouvée proche du point {idx+1}")
                    QgsProject.instance().removeMapLayer(single_point_layer.id())
                    continue

                materiau = str(nearest_line["MATERIAU"]).strip().upper()
                diametre = float(nearest_line["DIAMETRE"])
                travel_cost = get_travel_cost(materiau, diametre)

                # Calcul zone de desserte pour ce point
                service_area_params = {
                    'INPUT': densified_layer.id(),
                    'START_POINTS': QgsProcessingFeatureSourceDefinition(single_point_layer.id(), False),
                    'STRATEGY': 0,  # Distance-based
                    'DEFAULT_DIRECTION': 2,
                    'DEFAULT_SPEED': 50,
                    'TRAVEL_COST': travel_cost,
                    'INCLUDE_BOUNDS': False,
                    'OUTPUT': 'memory:'
                }
                service_area_result = processing.run("qgis:serviceareafromlayer", service_area_params)
                service_area_layer = service_area_result['OUTPUT']

                # Buffer 1 mètre autour
                buffer_params = {
                    'INPUT': service_area_layer,
                    'DISTANCE': 1,
                    'SEGMENTS': 5,
                    'END_CAP_STYLE': 0,
                    'JOIN_STYLE': 0,
                    'MITER_LIMIT': 2,
                    'DISSOLVE': True,
                    'OUTPUT': 'memory:'
                }
                buffer_result = processing.run("native:buffer", buffer_params)
                buffer_layer = buffer_result['OUTPUT']

                zones_ecoute.append(buffer_layer)

                # Supprimer la couche temporaire point
                QgsProject.instance().removeMapLayer(single_point_layer.id())

                # Mise à jour barre de progression
                self.dlg.progressBar.setValue(30 + int(((idx + 1) / total_points) * 60))

            if not zones_ecoute:
                QMessageBox.critical(self.dlg, "Erreur", "Aucune zone de desserte créée")
                QgsProject.instance().removeMapLayer(densified_layer.id())
                return

            # Fusionner tous les tampons
            merge_params = {
                'LAYERS': zones_ecoute,
                'OUTPUT': 'memory:'
            }
            merge_result = processing.run("native:mergevectorlayers", merge_params)
            merged_layer = merge_result['OUTPUT']
            merged_layer.setName("Zones d'écoute")
            QgsProject.instance().addMapLayer(merged_layer)

            # Supprimer couche densifiée pour nettoyage
            QgsProject.instance().removeMapLayer(densified_layer.id())

            self.dlg.progressBar.setValue(100)
            self.iface.messageBar().pushMessage("Info", "Zones d'écoute créées et fusionnées avec tampon.", level=0, duration=5)

        except Exception as e:
            QMessageBox.critical(self.dlg, "Erreur", str(e))
            self.dlg.progressBar.setValue(0)

def get_travel_cost(materiau, diametre):
    print(f"[DEBUG] RECU: MATERIAU='{materiau}', DIAMETRE={diametre}")
    rules = [
        {"MATERIAU": "Plomb", "MIN_DIAM": 1, "MAX_DIAM": 100, "TRAVEL_COST": 20},
        {"MATERIAU": "Acier", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 123},
        {"MATERIAU": "Acier", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 90},
        {"MATERIAU": "Acier", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 55},
        {"MATERIAU": "AMCI", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 61},
        {"MATERIAU": "AMCI", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 68},
        {"MATERIAU": "AMCI", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 43.5},
        {"MATERIAU": "BETON", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 56},
        {"MATERIAU": "BETON", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 54},
        {"MATERIAU": "BETON", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 58},
        {"MATERIAU": "FO_BLUTO", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 111},
        {"MATERIAU": "FO_BLUTO", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 74},
        {"MATERIAU": "FO_BLUTO", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 44},
        {"MATERIAU": "FO_DUCTI", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 111},
        {"MATERIAU": "FO_DUCTI", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 74},
        {"MATERIAU": "FO_DUCTI", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 44},
        {"MATERIAU": "FO_GRISE", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 122},
        {"MATERIAU": "FO_GRISE", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 88},
        {"MATERIAU": "FO_GRISE", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 53},
        {"MATERIAU": "FO_INCO", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 111},
        {"MATERIAU": "FO_INCO", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 74},
        {"MATERIAU": "FO_INCO", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 44},
        {"MATERIAU": "FO_REHAB", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 111},
        {"MATERIAU": "FO_REHAB", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 74},
        {"MATERIAU": "FO_REHAB", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 44},
        {"MATERIAU": "PE_INCO", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 52},
        {"MATERIAU": "PE_INCO", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 36},
        {"MATERIAU": "PE_INCO", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 25},
        {"MATERIAU": "PEBLAN", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 52},
        {"MATERIAU": "PEBLAN", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 36},
        {"MATERIAU": "PEBLAN", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 25},
        {"MATERIAU": "PEBLEU", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 52},
        {"MATERIAU": "PEBLEU", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 36},
        {"MATERIAU": "PEBLEU", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 25},
        {"MATERIAU": "PENOIR", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 52},
        {"MATERIAU": "PENOIR", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 36},
        {"MATERIAU": "PENOIR", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 25},
        {"MATERIAU": "PRV", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 52},
        {"MATERIAU": "PRV", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 36},
        {"MATERIAU": "PRV", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 25},
        {"MATERIAU": "PVCBIO", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 52},
        {"MATERIAU": "PVCBIO", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 36},
        {"MATERIAU": "PVCBIO", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 25},
        {"MATERIAU": "PVCINC", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 52},
        {"MATERIAU": "PVCINC", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 36},
        {"MATERIAU": "PVCINC", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 25},
        {"MATERIAU": "PVCMON", "MIN_DIAM": 1, "MAX_DIAM": 200, "TRAVEL_COST": 52},
        {"MATERIAU": "PVCMON", "MIN_DIAM": 201, "MAX_DIAM": 300, "TRAVEL_COST": 36},
        {"MATERIAU": "PVCMON", "MIN_DIAM": 301, "MAX_DIAM": 400, "TRAVEL_COST": 25},
    ]

    for rule in rules:
        if materiau == rule["MATERIAU"]:
            print(f"[DEBUG] MATCH: Rule {rule}")
            if rule["MIN_DIAM"] <= diametre <= rule["MAX_DIAM"]:
                print(f"[DEBUG] DIAM ok => {rule['TRAVEL_COST']}")
                return rule["TRAVEL_COST"]

    print("[DEBUG] AUCUNE CORRESPONDANCE => 100 par défaut")
    return 100
