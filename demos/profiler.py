#%%
# Imports

import argparse
import os
import sys

sys.path.append("../")
os.environ["TORCH_HOME"] = "/media/hdd/Datasets/"

import glob

import albumentations
import pandas as pd
import torch
import torch.nn as nn
from albumentations.pytorch import ToTensorV2
from efficientnet_pytorch import EfficientNet
from sklearn import metrics, model_selection, preprocessing
from torch.nn import functional as F

import zeus
from zeus.callbacks import (EarlyStopping, GradientClipping, PlotLoss,
                            PruningCallback, TensorBoardLogger, TrainingTime)
from zeus.datasets import ImageDataset
from zeus.metrics import LabelSmoothingCrossEntropy
from zeus.utils.model_helpers import *

#%%
# Defining

## Params

INPUT_PATH = "/media/hdd/Datasets/blindness/"
MODEL_PATH = "./models/"
MODEL_NAME = os.path.basename("blindness.pt")
TRAIN_BATCH_SIZE = 64  # lower batch sizes
VALID_BATCH_SIZE = 64
IMAGE_SIZE = 192

#%%
class Model(zeus.Model):
    def __init__(self, num_classes):
        super().__init__()

        self.effnet = EfficientNet.from_pretrained("efficientnet-b0")
        self.dropout = nn.Dropout(0.1)
        self.out = nn.Linear(1280, num_classes)

    def monitor_metrics(self, outputs, targets):
        outputs = torch.argmax(outputs, dim=1).cpu().detach().numpy()
        targets = targets.cpu().detach().numpy()
        accuracy = metrics.accuracy_score(targets, outputs)
        return {"accuracy": accuracy}

    def fetch_optimizer(self):
        opt = torch.optim.AdamW(self.parameters(), lr=1e-4)
        return opt

    def forward(self, image, targets=None):
        batch_size, _, _, _ = image.shape

        x = self.effnet.extract_features(image)
        x = F.adaptive_avg_pool2d(x, 1).reshape(batch_size, -1)
        outputs = self.out(self.dropout(x))

        if targets is not None:
            #  loss = nn.CrossEntropyLoss()(outputs, targets)
            loss = LabelSmoothingCrossEntropy()(outputs, targets)
            metrics = self.monitor_metrics(outputs, targets)
            return outputs, loss, metrics
        return outputs, 0, {}


#%%
train_aug = albumentations.Compose(
    [
        albumentations.Resize(IMAGE_SIZE, IMAGE_SIZE),
        albumentations.Transpose(p=0.5),
        albumentations.HorizontalFlip(p=0.5),
        albumentations.VerticalFlip(p=0.5),
        albumentations.ShiftScaleRotate(p=0.5),
        albumentations.HueSaturationValue(
            hue_shift_limit=0.2, sat_shift_limit=0.2, val_shift_limit=0.2, p=0.5
        ),
        albumentations.RandomBrightnessContrast(
            brightness_limit=(-0.1, 0.1), contrast_limit=(-0.1, 0.1), p=0.5
        ),
        albumentations.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
            max_pixel_value=255.0,
            p=1.0,
        ),
    ],
    p=1.0,
)

valid_aug = albumentations.Compose(
    [
        albumentations.Resize(IMAGE_SIZE, IMAGE_SIZE),
        albumentations.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
            max_pixel_value=255.0,
            p=1.0,
        ),
    ],
    p=1.0,
)

#%%
#  Data pre process

df = pd.read_csv(INPUT_PATH + "trainLabels.csv")
df.head(3)

df["image"] = INPUT_PATH + "trainImages/" + df["image"] + ".jpg"
df.head(3)

# SUBSET REMOVE LATER
df = df.head(5000)

from sklearn.model_selection import train_test_split

train_images, valid_images = train_test_split(df, test_size=0.33)

train_image_paths, valid_image_paths = (
    train_images["image"].values,
    valid_images["image"].values,
)

train_targets, valid_targets = (
    train_images["level"].values,
    valid_images["level"].values,
)


lbl_enc = preprocessing.LabelEncoder()
train_targets = lbl_enc.fit_transform(train_targets)
valid_targets = lbl_enc.transform(valid_targets)
#%%
# Training
train_dataset = ImageDataset(
    image_paths=train_image_paths,
    targets=train_targets,
    augmentations=train_aug,
)

valid_dataset = ImageDataset(
    image_paths=valid_image_paths,
    targets=valid_targets,
    augmentations=valid_aug,
)
# -
#%%
#  Callbacks
model = Model(num_classes=len(lbl_enc.classes_))

es = EarlyStopping(
    monitor="valid_loss",
    model_path=os.path.join(MODEL_PATH, MODEL_NAME + ".bin"),
    patience=3,
    mode="min",
)

tb = TensorBoardLogger()
grc = GradientClipping(5)
pr = PruningCallback()
tt = TrainingTime()

count_parameters(model, showtable=False)
#%%
EPOCHS = 2
# pl = PlotLoss(EPOCHS)

model.fit(
    train_dataset,
    valid_dataset=valid_dataset,
    train_bs=TRAIN_BATCH_SIZE,
    valid_bs=VALID_BATCH_SIZE,
    device="cuda",
    epochs=EPOCHS,
    callbacks=[grc, tb, pr, tt],
    fp16=True,
    pin_mem=True,
)
# -
