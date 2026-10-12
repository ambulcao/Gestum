import os
import time
import math

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions, HandLandmarker, HandLandmarkerOptions
from mediapipe.tasks.python.vision.hand_landmarker import HandLandmarksConnections
from mediapipe.tasks.python.vision.core.vision_task_running_mode import (
    VisionTaskRunningMode,
)

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")
FACE_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blaze_face_short_range.tflite")


class handDetector():
    def __init__(self, mode=False, maxHands=1, detection_confidence=0.8, tracking_confidence=0.8):
        self.mode = mode
        self.maxHands = maxHands
        self.detection_confidence = detection_confidence
        self.tracking_confidence = tracking_confidence
        self.tipIds = [4, 8, 12, 16, 20]  # [polegar, indicador, médio, anelar, mínimo]
        self.lmList = []
        self.landmarks = []
        self.todas = []
        self._last_timestamp = 0

        if not os.path.isfile(MODEL_PATH):
            raise FileNotFoundError(
                f"Modelo de mão não encontrado em {MODEL_PATH}"
            )

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=VisionTaskRunningMode.VIDEO,
            num_hands=self.maxHands,
            min_hand_detection_confidence=self.detection_confidence,
            min_hand_presence_confidence=self.detection_confidence,
            min_tracking_confidence=self.tracking_confidence,
        )
        self.hands = HandLandmarker.create_from_options(options)
        self.connections = HandLandmarksConnections.HAND_CONNECTIONS

    def findHands(self, img, draw=True):
        imgRGB = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(imgRGB),
        )
        timestamp = int(time.monotonic() * 1000)
        if timestamp <= self._last_timestamp:
            timestamp = self._last_timestamp + 1
        self._last_timestamp = timestamp

        result = self.hands.detect_for_video(mp_image, timestamp)
        self.todas = list(result.hand_landmarks) if result.hand_landmarks else []
        self.landmarks = []

        if draw:
            for landmarks in self.todas:
                self.desenhar_mao(img, landmarks)
        return img

    def desenhar_mao(self, img, landmarks, cor_linha=(57, 255, 20)):
        h, w = img.shape[:2]
        points = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
        for connection in self.connections:
            cv2.line(img, points[connection.start], points[connection.end], cor_linha, 2)
        for point in points:
            cv2.circle(img, point, 2, (255, 0, 255), cv2.FILLED)

    def listar_maos(self, img):
        """Devolve cada mão com a caixa e o centro, na ordem do detector."""
        h, w = img.shape[:2]
        maos = []
        for landmarks in self.todas:
            xs, ys = [], []
            for lm in landmarks:
                xs.append(int(lm.x * w))
                ys.append(int(lm.y * h))
            if not xs:
                continue
            maos.append({
                "landmarks": landmarks,
                "cx": sum(xs) / len(xs),
                "cy": sum(ys) / len(ys),
                "bbox": (min(xs), min(ys), max(xs), max(ys)),
            })
        return maos

    def findPosition(self, img, handNo=0, draw=True):
        self.lmList = []
        xList = []
        yList = []
        bbox = []

        if self.landmarks:
            h, w = img.shape[:2]
            for landmark_id, lm in enumerate(self.landmarks):
                cx, cy = int(lm.x * w), int(lm.y * h)
                self.lmList.append([landmark_id, cx, cy])
                xList.append(cx)
                yList.append(cy)

                if draw and landmark_id in self.tipIds:
                    cv2.circle(img, (cx, cy), 5, (255, 0, 0), cv2.FILLED)

            if xList and yList:
                bbox = min(xList), min(yList), max(xList), max(yList)
                if draw:
                    cv2.rectangle(img, (bbox[0] - 20, bbox[1] - 20),
                                  (bbox[2] + 20, bbox[3] + 20), (0, 255, 0), 2)

        return self.lmList, bbox

    def fingersUp(self):
        fingers = []
        if len(self.lmList) >= 21:
            # Polegar aberto: a ponta fica mais longe do pulso do que a junta
            pulso = self.lmList[0]
            ponta = self.lmList[4]
            junta = self.lmList[3]
            distancia_ponta = math.hypot(ponta[1] - pulso[1], ponta[2] - pulso[2])
            distancia_junta = math.hypot(junta[1] - pulso[1], junta[2] - pulso[2])
            fingers.append(1 if distancia_ponta > distancia_junta * 1.15 else 0)

            # Demais dedos
            for finger_id in range(1, 5):
                if self.lmList[self.tipIds[finger_id]][2] < self.lmList[self.tipIds[finger_id] - 2][2]:
                    fingers.append(1)
                else:
                    fingers.append(0)
        return fingers

    def findDistance(self, p1, p2, img=None, draw=True, r=15, t=3):
        x1, y1 = self.lmList[p1][1:]
        x2, y2 = self.lmList[p2][1:]
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

        if draw and img is not None:
            cv2.line(img, (x1, y1), (x2, y2), (255, 0, 255), t)
            cv2.circle(img, (x1, y1), r, (255, 0, 255), cv2.FILLED)
            cv2.circle(img, (x2, y2), r, (255, 0, 255), cv2.FILLED)
            cv2.circle(img, (cx, cy), r, (0, 0, 255), cv2.FILLED)

        length = math.hypot(x2 - x1, y2 - y1)
        return length, [x1, y1, x2, y2, cx, cy]


class detectorPessoas:
    """Acha os rostos. O maior é a pessoa mais perto da câmera."""

    def __init__(self):
        if not os.path.isfile(FACE_MODEL_PATH):
            raise FileNotFoundError(f"Modelo de rosto não encontrado em {FACE_MODEL_PATH}")
        options = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=FACE_MODEL_PATH),
            running_mode=VisionTaskRunningMode.VIDEO,
            min_detection_confidence=0.5,
        )
        self.detector = FaceDetector.create_from_options(options)
        self._last_timestamp = 0

    def detectar(self, img):
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        timestamp = int(time.monotonic() * 1000)
        if timestamp <= self._last_timestamp:
            timestamp = self._last_timestamp + 1
        self._last_timestamp = timestamp
        result = self.detector.detect_for_video(mp_image, timestamp)
        rostos = []
        for detection in result.detections:
            box = detection.bounding_box
            x, y = int(box.origin_x), int(box.origin_y)
            largura, altura = int(box.width), int(box.height)
            if largura < 20 or altura < 20:
                continue
            rostos.append({
                "x": x,
                "y": y,
                "w": largura,
                "h": altura,
                "cx": x + largura / 2,
                "cy": y + altura / 2,
                "area": largura * altura,
            })
        rostos.sort(key=lambda rosto: rosto["area"], reverse=True)
        return rostos
