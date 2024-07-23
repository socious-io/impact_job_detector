from random import sample
import joblib
import yake
import pandas as pd
from sklearn.svm import OneClassSVM
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.tree import DecisionTreeClassifier
from sklearn.neighbors import NearestNeighbors
from nltk.stem import WordNetLemmatizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score
import re
from nltk.corpus import stopwords
import nltk
import numpy as np
from time import time
from fuzzywuzzy import fuzz

nltk.download('punkt')
nltk.download('stopwords')
nltk.download('wordnet')

impact_keywords = [
    "sustainability", "sustainable development", "environmental protection", "green energy",
    "social impact", "community development", "social justice", "equity and inclusion", "human rights",
    "economic development", "poverty alleviation", "economic empowerment", "microfinance", "fair trade",
    "health and well-being", "public health", "mental health support", "healthcare access", "wellness programs",
    "education and literacy", "educational outreach", "literacy programs", "STEM education", "lifelong learning",
    "humanitarian aid", "disaster relief", "refugee support", "crisis intervention", "food security",
    "innovation and technology", "social innovation", "tech for good", "digital inclusion", "smart cities",
    "governance and policy", "advocacy and policy", "social impact"
]


class OutlierEnsemble(BaseEstimator, ClassifierMixin):
    def __init__(self):
        self.knn_model = NearestNeighbors(n_neighbors=8)
        self.svm_model = OneClassSVM()
        self.max_pair = ()
        self.max_distance = 0
        self.svm_score = 0
        self.threshhold = 0

    def fit(self, X, y=None):
        # Fit both models on the training data
        self.knn_model.fit(X)
        self.svm_model.fit(X)
        return self

    def max_distance_between_points(self, points):
        max_distance = 0
        pair = ()
        num_points = len(points)
        for i in range(num_points):
            for j in range(i + 1, num_points):
                distance = np.linalg.norm(points[i] - points[j])
                if distance > max_distance:
                    max_distance = distance
                    pair = (points[i], points[j])
        return pair, max_distance

    def predict(self, X, learn=False):
        # Predict outlier scores using both models
        distances, _ = self.knn_model.kneighbors(X)
        svm_scores = self.svm_model.decision_function(X)
        # Combine scores using simple voting

        if learn:
            pairs, distance = self.max_distance_between_points(distances)
            self.max_pair = pairs
            self.max_distance = distance
            self.svm_score = np.mean(svm_scores)

        scores = []
        for i, item in enumerate(svm_scores):
            _, distance = self.max_distance_between_points(
                distances[i] + self.max_pair)
            scores.append((10 - abs(self.max_distance - distance)) + item)

        if learn:
            self.threshhold = np.mean(
                scores) + ((np.max(scores) - np.mean(scores)) / 2)

        return [1 if s <= self.threshhold else 0 for s in scores]


class ImpactDetectorModel:
    K_N_COUNT = 8

    STATUS_INIT = 'init'
    STATUS_TRAINING = 'training'
    STATUS_TRAINED = 'trained'

    TEST_DATA_SELECT_PERCENT = 10
    STOP_WORDS = set(stopwords.words('english'))
    LEMMATIZER = WordNetLemmatizer()
    YAKE = yake.KeywordExtractor(n=3, dedupLim=0.9, top=50, features=None)
    VECTORIZER = TfidfVectorizer()

    @property
    def name(self):
        return 'impact_detector'

    @property
    def model_name(self):
        return '%s_model.pkl' % self.name

    @property
    def vectorizer_name(self):
        return '%s_vectorizer.pkl' % self.name

    def __init__(self, data_loader_func) -> None:
        self.data_loader_func = data_loader_func
        self.accuracy = 0
        self.model = None
        self.status = self.STATUS_INIT
        self.avg_distance = 0

    def load_data(self):
        data = self.data_loader_func()
        length = len(data)
        if length < 10:
            raise ValueError('data length is too low')
        test_sample_count = int(length * self.TEST_DATA_SELECT_PERCENT / 100)
        train_sample_count = length - test_sample_count
        self.data = pd.DataFrame(sample(data, train_sample_count))
        self.test_data = pd.DataFrame(sample(data, test_sample_count))
        print(
            f'Fetched {len(data)} of total data for ({len(self.data)}, {len(self.test_data)}) {self.name} ')

    def clean_text(self, text):
        text = re.sub('<.*?>', '', text)  # Remove HTML tags
        text = re.sub('[^\w\s]', '', text)  # Remove punctuation
        text = text.lower()  # Convert to lowercase
        text = re.sub(r"_+", " ", text)
        return text

    def obj_to_text(self, obj):
        values = [
            ' '.join(val) if isinstance(val, list) else val
            for key, val in obj.items()
            if key != 'id' and (isinstance(val, str) or isinstance(val, list))
        ]
        return ' '.join(values)

    def get_train_model(self):
        return OutlierEnsemble()

    def parallel_preprocess(self, data):
        inprocess_yake = yake.KeywordExtractor(
            n=3, dedupLim=0.9, top=50, features=None)
        name = self.name

        class Tick:
            def __init__(self) -> None:
                self.lock = False
                self.last_time = time()
                self.last_percent = 0

        ticker = Tick()

        def percentage(index):
            p = ((index+1) * 100) / len(data)
            now = time()
            if (now - ticker.last_time > 600 and not ticker.lock and ticker.last_percent < p):
                ticker.lock = True
                ticker.last_time = now
                ticker.last_percent = p
                print(f'{name} -> {p:.2f}% of text proccess done')
                ticker.lock = False

        def clean_text(text):
            text = re.sub('<.*?>', '', text)  # Remove HTML tags
            text = re.sub('[^\w\s]', '', text)  # Remove punctuation
            text = text.lower()  # Convert to lowercase
            text = re.sub(r"_+", " ", text)
            return text

        def preprocess_text(text, index):
            text = clean_text(text)
            keywords = inprocess_yake.extract_keywords(text)
            result = ' '.join([k[0] for k in keywords])
            words = set(result.split())
            percentage(index)
            return ' '.join(words)

        # Separate function for preprocessing
        return joblib.Parallel(n_jobs=-1)(
            joblib.delayed(preprocess_text)(self.obj_to_text(item), i) for i, item in enumerate(data)
        )

    def train(self, force=False):
        if self.status == self.STATUS_TRAINING:
            return

        self.status = self.STATUS_TRAINING
        self.load_data()
        if not force:
            try:
                model = joblib.load(self.model_name)
                self.VECTORIZER = joblib.load(self.vectorizer_name)
                self.model = model
                self.status = self.STATUS_TRAINED
                self.get_score()
                return
            except Exception:
                pass
        print(
            f'-----------  {self.name} train start processing texts ---------- ')
        data_items = [item for _, item in self.data.iterrows()]
        processed_data = self.parallel_preprocess(data_items)
        print(f'-----------  {self.name} start training ----------- ')
        tfidf_matrix = self.VECTORIZER.fit_transform(processed_data)
        self.model = self.get_train_model()
        self.model.fit(tfidf_matrix)
        self.get_score()
        joblib.dump(self.model, self.model_name)
        joblib.dump(self.VECTORIZER, self.vectorizer_name)
        self.status = self.STATUS_TRAINED
        print(f'----------- {self.name} train done ---------------')

    def predictions(self, distances):
        return [min(dis) < 1 for dis in distances]

    def get_score(self):
        data_items = [item for _, item in self.test_data.iterrows()]
        processed_query_data = self.parallel_preprocess(data_items)
        query_matrix = self.VECTORIZER.transform(processed_query_data)
        predictions = self.model.predict(query_matrix, learn=True)
        self.accuracy = accuracy_score(
            [True for _ in data_items], predictions)
        print(f'---- {self.name} accuracy is {self.accuracy} ------')

    def fuzzy_match(self, description):
        keywords = self.YAKE.extract_keywords(description)
        ratios = []
        keywords = [k[0] for k in keywords]
        for keyword in keywords:
            keyword_ratios = [fuzz.ratio(keyword.lower(), impact_keyword.lower(
            )) / 100.0 for impact_keyword in impact_keywords]
            if keyword_ratios:
                max_ratio = max(keyword_ratios)
                ratios.append(max_ratio)
        return np.max(ratios)

    def predict(self, query):
        if not isinstance(query, (list, tuple, np.ndarray)):
            query = [query]

        query_data = pd.DataFrame(query)
        data_items = [item for _, item in query_data.iterrows()]
        processed_query_data = self.parallel_preprocess(data_items)

        query_matrix = self.VECTORIZER.transform(processed_query_data)
        predictions = self.model.predict(query_matrix)
        results = []
        for i, p in enumerate(predictions):
            results.append(self.fuzzy_match(query[i]) > 0.5 or p)
        return results
