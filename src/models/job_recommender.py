from random import sample
import joblib
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from transformers import T5ForConditionalGeneration, T5Tokenizer
from nltk.stem import WordNetLemmatizer
from sklearn.feature_extraction.text import TfidfVectorizer
from nltk.tokenize import word_tokenize
import re
from nltk.corpus import stopwords
import nltk
import string
import numpy as np

nltk.download('punkt')
nltk.download('stopwords')
nltk.download('wordnet')


class TrainModel:
    K_N_COUNT = 10
    TEST_DATA_SELECT_PERCENT = 30
    STOP_WORDS = set(stopwords.words('english'))
    LEMMATIZER = WordNetLemmatizer()
    PROCCESSED_TEXTS_DB = 'processed_texts.db'

    SUMMARIZER_MODEL_NAME = 't5-small'
    TOKENIZER = T5Tokenizer.from_pretrained(SUMMARIZER_MODEL_NAME)
    SUMMARIZER = T5ForConditionalGeneration.from_pretrained(
        SUMMARIZER_MODEL_NAME)

    VECTORIZER = TfidfVectorizer()
    MODEL_NAME = 'job_recommender.pkl'
    VECTORIZER_NAME = 'job_recommender_vectorizer.pkl'

    def __init__(self, data) -> None:
        length = len(data)
        if length < 10:
            raise ValueError('data length is too low')
        test_sample_count = int(length * self.TEST_DATA_SELECT_PERCENT / 100)
        train_sample_count = length - test_sample_count

        self.test_data = pd.DataFrame(sample(data, test_sample_count))
        self.data = pd.DataFrame(sample(data, train_sample_count))
        self.accuracy = 0
        self.model = None

    def clean_text(self, text):
        text = re.sub('<.*?>', '', text)  # Remove HTML tags
        text = re.sub('[^\w\s]', '', text)  # Remove punctuation
        text = text.lower()  # Convert to lowercase
        return text

    def preprocess_text(self, text):

        text = self.clean_text(text)
        word_tokens = word_tokenize(text)
        # Lemmatization
        lemmatized_words = [self.LEMMATIZER.lemmatize(
            word) for word in word_tokens]
        # Remove punctuation
        words_without_punct = [
            word for word in lemmatized_words if word not in string.punctuation]
        filtered_text = [
            word for word in words_without_punct if word.casefold() not in self.STOP_WORDS]

        text = " ".join(filtered_text).lower()
        return self.clean_text(text)

    def extract_keywords(self, matrix):
        keywords = []
        for vector in matrix.toarray():
            # Get indices sorted by TF-IDF values
            sorted_indices = vector.argsort()[-50:][::-1]
            # Map indices to terms
            keywords.append(' '.join([self.VECTORIZER.get_feature_names_out()[i]
                            for i in sorted_indices]))

        return keywords

    def obj_to_text(self, obj):
        return ' '.join([obj[key] if key != 'id' and obj[key] is not None else '' for key in obj.keys()])

    def train(self, force=False):
        if not force:
            try:
                model = joblib.load(self.MODEL_NAME)
                self.VECTORIZER = joblib.load(self.VECTORIZER_NAME)
                self.model = model
                return
            except Exception:
                pass
        proccessed_data = [self.preprocess_text(
            self.obj_to_text(item)) for _, item in self.data.iterrows()]
        tfidf_matrix = self.VECTORIZER.fit_transform(proccessed_data)
        tfidf_matrix = self.VECTORIZER.transform(
            self.extract_keywords(tfidf_matrix))
        self.model = NearestNeighbors(n_neighbors=self.K_N_COUNT)
        self.model.fit(tfidf_matrix)

    def predict(self, query):
        query_data = pd.DataFrame(query)

        proccessed_query_data = [self.preprocess_text(
            self.obj_to_text(item)) for _, item in query_data.iterrows()]

        query_matrix = self.VECTORIZER.transform(proccessed_query_data)
        query_matrix = self.VECTORIZER.transform(
            self.extract_keywords(query_matrix))

        _, indices = self.model.kneighbors(query_matrix)
        elements = list(dict.fromkeys(
            element for sublist in indices for element in sublist))
        return self.data.iloc[elements]['id'].values