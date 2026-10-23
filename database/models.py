"""Modelos SQLAlchemy do FitOS.

Convenções:
- Dados pessoais (medidas, treinos, cardápios, estoque, listas) pertencem a um perfil.
- Catálogos (alimentos, exercícios, produtos, preços, estabelecimentos) são compartilhados
  entre perfis da mesma instalação, para não duplicar cadastro.
- Valores monetários e quantidades de compra usam Numeric/Decimal.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Money = Numeric(12, 2, asdecimal=True)
Qty = Numeric(14, 3, asdecimal=True)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# --------------------------------------------------------------------------- perfil

class Profile(TimestampMixin, Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    age: Mapped[int] = mapped_column(Integer)
    weight_kg: Mapped[float] = mapped_column(Float)
    height_cm: Mapped[float] = mapped_column(Float)
    # opcionais — None significa "não informado", nunca um valor presumido
    sex: Mapped[str | None] = mapped_column(String(1))  # "M" | "F"
    goal: Mapped[str | None] = mapped_column(String(20))
    target_weight_kg: Mapped[float | None] = mapped_column(Float)
    activity_level: Mapped[str | None] = mapped_column(String(20))
    experience: Mapped[str | None] = mapped_column(String(20))
    training_weekdays: Mapped[list | None] = mapped_column(JSON)  # 0=segunda … 6=domingo
    session_minutes: Mapped[int | None] = mapped_column(Integer)
    restrictions: Mapped[str | None] = mapped_column(Text)
    preferences: Mapped[str | None] = mapped_column(Text)
    allergies: Mapped[str | None] = mapped_column(Text)
    injuries: Mapped[str | None] = mapped_column(Text)
    equipment: Mapped[list | None] = mapped_column(JSON)
    monthly_food_budget: Mapped[Decimal | None] = mapped_column(Money)
    people_count: Mapped[int] = mapped_column(Integer, default=1)
    # código de acesso do perfil (PBKDF2 com sal); None = perfil antigo, entra com o código da instalação
    access_hash: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    measurements: Mapped[list[Measurement]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (Index("ix_measurements_profile_date", "profile_id", "measured_on"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    measured_on: Mapped[date] = mapped_column(Date)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    abdomen_cm: Mapped[float | None] = mapped_column(Float)
    waist_cm: Mapped[float | None] = mapped_column(Float)
    arm_cm: Mapped[float | None] = mapped_column(Float)
    chest_cm: Mapped[float | None] = mapped_column(Float)
    hip_cm: Mapped[float | None] = mapped_column(Float)
    thigh_cm: Mapped[float | None] = mapped_column(Float)
    photo_path: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    profile: Mapped[Profile] = relationship(back_populates="measurements")


# --------------------------------------------------------------------------- exercícios e treinos

class Exercise(Base):
    __tablename__ = "exercises"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_exercise_source"),
        Index("ix_exercises_body_part", "body_part"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # exercisedb | wger | manual
    source_id: Mapped[str] = mapped_column(String(64))
    name_original: Mapped[str] = mapped_column(String(160))
    name_pt: Mapped[str | None] = mapped_column(String(160))
    body_part: Mapped[str | None] = mapped_column(String(40))
    primary_muscle: Mapped[str | None] = mapped_column(String(60))
    secondary_muscles: Mapped[list | None] = mapped_column(JSON)
    equipment: Mapped[str | None] = mapped_column(String(60))
    difficulty: Mapped[str | None] = mapped_column(String(20))
    instructions: Mapped[str | None] = mapped_column(Text)
    common_errors: Mapped[str | None] = mapped_column(Text)
    gif_url: Mapped[str | None] = mapped_column(String(400))
    video_url: Mapped[str | None] = mapped_column(String(400))
    media_source: Mapped[str | None] = mapped_column(String(120))
    license: Mapped[str | None] = mapped_column(String(120))
    attribution: Mapped[str | None] = mapped_column(String(255))
    slot: Mapped[str | None] = mapped_column(String(30))  # padrão de movimento (curadoria local)
    is_core: Mapped[bool] = mapped_column(Boolean, default=False)  # exercícios curados p/ geração


class WorkoutPlan(TimestampMixin, Base):
    __tablename__ = "workout_plans"
    __table_args__ = (Index("ix_workout_plans_profile", "profile_id", "is_active"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("workout_plans.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    origin: Mapped[str] = mapped_column(String(20), default="local")  # local | gemini | manual
    change_note: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)

    days: Mapped[list[WorkoutDay]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="WorkoutDay.position")


class WorkoutDay(Base):
    __tablename__ = "workout_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("workout_plans.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    weekday: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))

    plan: Mapped[WorkoutPlan] = relationship(back_populates="days")
    exercises: Mapped[list[PlannedExercise]] = relationship(
        back_populates="day", cascade="all, delete-orphan", order_by="PlannedExercise.position")


class PlannedExercise(Base):
    """Séries planejadas de um exercício dentro de um dia de treino."""
    __tablename__ = "planned_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("workout_days.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    position: Mapped[int] = mapped_column(Integer)
    sets: Mapped[int] = mapped_column(Integer)
    reps_min: Mapped[int] = mapped_column(Integer)
    reps_max: Mapped[int] = mapped_column(Integer)
    rest_seconds: Mapped[int] = mapped_column(Integer, default=90)
    target_load_kg: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    day: Mapped[WorkoutDay] = relationship(back_populates="exercises")
    exercise: Mapped[Exercise] = relationship()


class DayOverride(Base):
    """Troca do treino de uma data específica (ex.: fazer o treino de quinta hoje)."""
    __tablename__ = "day_overrides"
    __table_args__ = (UniqueConstraint("profile_id", "on_date", name="uq_override_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    on_date: Mapped[date] = mapped_column(Date)
    day_id: Mapped[int | None] = mapped_column(ForeignKey("workout_days.id", ondelete="CASCADE"))  # None = descanso


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (Index("ix_sessions_profile_date", "profile_id", "performed_on"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("workout_plans.id", ondelete="SET NULL"))
    day_id: Mapped[int | None] = mapped_column(ForeignKey("workout_days.id", ondelete="SET NULL"))
    performed_on: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    fatigue: Mapped[int | None] = mapped_column(Integer)  # esforço percebido 1–10
    pain: Mapped[bool] = mapped_column(Boolean, default=False)
    pain_notes: Mapped[str | None] = mapped_column(Text)
    recovery: Mapped[str | None] = mapped_column(String(20))  # boa | regular | ruim
    notes: Mapped[str | None] = mapped_column(Text)

    sets: Mapped[list[SetLog]] = relationship(back_populates="session", cascade="all, delete-orphan")


class SetLog(Base):
    """Série efetivamente executada."""
    __tablename__ = "set_logs"
    __table_args__ = (Index("ix_set_logs_exercise", "exercise_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("workout_sessions.id", ondelete="CASCADE"), index=True)
    planned_exercise_id: Mapped[int | None] = mapped_column(ForeignKey("planned_exercises.id", ondelete="SET NULL"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    set_number: Mapped[int] = mapped_column(Integer)
    load_kg: Mapped[float | None] = mapped_column(Float)
    reps: Mapped[int | None] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    difficulty: Mapped[str | None] = mapped_column(String(20))  # facil | ok | dificil | falha

    session: Mapped[WorkoutSession] = relationship(back_populates="sets")


# --------------------------------------------------------------------------- alimentos e nutrição

class Food(Base):
    """Alimento com composição por 100 g de porção comestível."""
    __tablename__ = "foods"
    __table_args__ = (Index("ix_foods_name", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    taco_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(160))
    short_name: Mapped[str | None] = mapped_column(String(60))
    category: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(10), default="pronto")  # cru | cozido | pronto
    group: Mapped[str | None] = mapped_column(String(30))  # grupo de substituição (curadoria)
    raw_food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id"))
    yield_factor: Mapped[float | None] = mapped_column(Float)  # peso cozido / peso cru
    yield_source: Mapped[str | None] = mapped_column(String(160))
    edible_factor: Mapped[float] = mapped_column(Float, default=1.0)  # porção comestível / peso comprado
    edible_source: Mapped[str | None] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(80), default="TACO 4ª ed.")
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_core: Mapped[bool] = mapped_column(Boolean, default=False)

    nutrients: Mapped[FoodNutrients] = relationship(back_populates="food", uselist=False, cascade="all, delete-orphan")
    raw_food: Mapped[Food | None] = relationship(remote_side="Food.id")


class FoodNutrients(Base):
    __tablename__ = "food_nutrients"

    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"), primary_key=True)
    kcal: Mapped[float | None] = mapped_column(Float)
    protein_g: Mapped[float | None] = mapped_column(Float)
    carbs_g: Mapped[float | None] = mapped_column(Float)
    fat_g: Mapped[float | None] = mapped_column(Float)
    fiber_g: Mapped[float | None] = mapped_column(Float)
    sodium_mg: Mapped[float | None] = mapped_column(Float)
    moisture_g: Mapped[float | None] = mapped_column(Float)

    food: Mapped[Food] = relationship(back_populates="nutrients")


class Recipe(TimestampMixin, Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160))
    instructions: Mapped[str | None] = mapped_column(Text)
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    servings: Mapped[int] = mapped_column(Integer, default=1)
    origin: Mapped[str] = mapped_column(String(20), default="manual")

    ingredients: Mapped[list[RecipeIngredient]] = relationship(cascade="all, delete-orphan")


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    grams: Mapped[float] = mapped_column(Float)

    food: Mapped[Food] = relationship()


class MealPlan(TimestampMixin, Base):
    __tablename__ = "meal_plans"
    __table_args__ = (Index("ix_meal_plans_profile", "profile_id", "is_active"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    start_date: Mapped[date] = mapped_column(Date)
    days: Mapped[int] = mapped_column(Integer)
    people: Mapped[int] = mapped_column(Integer, default=1)
    origin: Mapped[str] = mapped_column(String(20), default="local")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("meal_plans.id", ondelete="SET NULL"))
    target_kcal: Mapped[float | None] = mapped_column(Float)
    target_protein_g: Mapped[float | None] = mapped_column(Float)
    budget: Mapped[Decimal | None] = mapped_column(Money)
    notes: Mapped[str | None] = mapped_column(Text)

    meals: Mapped[list[Meal]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="[Meal.day_index, Meal.position]")


class Meal(Base):
    __tablename__ = "meals"
    __table_args__ = (Index("ix_meals_plan_day", "plan_id", "day_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("meal_plans.id", ondelete="CASCADE"))
    day_index: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    meal_type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str | None] = mapped_column(String(160))
    preparation: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[MealPlan] = relationship(back_populates="meals")
    items: Mapped[list[MealItem]] = relationship(back_populates="meal", cascade="all, delete-orphan")


class MealItem(Base):
    __tablename__ = "meal_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id", ondelete="CASCADE"), index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    grams: Mapped[float] = mapped_column(Float)  # porção consumida, no estado do alimento

    meal: Mapped[Meal] = relationship(back_populates="items")
    food: Mapped[Food] = relationship()


# --------------------------------------------------------------------------- mercado

class Establishment(Base):
    __tablename__ = "establishments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)


class Product(Base):
    """Produto comprável, ligado ao alimento que ele fornece."""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(60))
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id"), index=True)
    brand: Mapped[str | None] = mapped_column(String(80))
    grams_per_unit: Mapped[float | None] = mapped_column(Float)  # p/ itens vendidos por unidade (ex.: ovo)
    density_g_ml: Mapped[float | None] = mapped_column(Float)  # p/ líquidos (ex.: leite)
    notes: Mapped[str | None] = mapped_column(Text)

    food: Mapped[Food | None] = relationship()
    quotes: Mapped[list[PriceQuote]] = relationship(back_populates="product", cascade="all, delete-orphan")


class PriceQuote(TimestampMixin, Base):
    """Cotação de preço: o conjunto das cotações forma o histórico de preços."""
    __tablename__ = "price_quotes"
    __table_args__ = (Index("ix_quotes_product_date", "product_id", "quoted_on"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    establishment_id: Mapped[int | None] = mapped_column(ForeignKey("establishments.id", ondelete="SET NULL"))
    price: Mapped[Decimal] = mapped_column(Money)
    package_qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(10))  # kg g l ml un duzia
    quoted_on: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="quotes")
    establishment: Mapped[Establishment | None] = relationship()


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(10))
    grams_per_unit: Mapped[float | None] = mapped_column(Float)
    expires_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    food: Mapped[Food] = relationship()


class ShoppingList(TimestampMixin, Base):
    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    meal_plan_id: Mapped[int | None] = mapped_column(ForeignKey("meal_plans.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    budget: Mapped[Decimal | None] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20), default="aberta")  # aberta | concluida

    items: Mapped[list[ShoppingItem]] = relationship(back_populates="shopping_list", cascade="all, delete-orphan")


class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("shopping_lists.id", ondelete="CASCADE"), index=True)
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("price_quotes.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(String(160))
    needed_base: Mapped[Decimal] = mapped_column(Qty)  # necessidade total (g, ml ou un)
    stock_base: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    to_buy_base: Mapped[Decimal] = mapped_column(Qty)
    base_unit: Mapped[str] = mapped_column(String(4))  # g | ml | un
    packages: Mapped[int | None] = mapped_column(Integer)
    package_label: Mapped[str | None] = mapped_column(String(60))
    estimated_cost: Mapped[Decimal | None] = mapped_column(Money)
    purchased: Mapped[bool] = mapped_column(Boolean, default=False)
    purchased_qty: Mapped[Decimal | None] = mapped_column(Qty)  # em embalagens
    paid_price: Mapped[Decimal | None] = mapped_column(Money)
    establishment_id: Mapped[int | None] = mapped_column(ForeignKey("establishments.id", ondelete="SET NULL"))

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="items")
    food: Mapped[Food | None] = relationship()
    product: Mapped[Product | None] = relationship()


class Purchase(TimestampMixin, Base):
    """Histórico de compras efetivadas (uma linha por item marcado como comprado)."""
    __tablename__ = "purchases"
    __table_args__ = (Index("ix_purchases_profile_date", "profile_id", "purchased_on"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    shopping_item_id: Mapped[int | None] = mapped_column(ForeignKey("shopping_items.id", ondelete="SET NULL"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    establishment_id: Mapped[int | None] = mapped_column(ForeignKey("establishments.id", ondelete="SET NULL"))
    purchased_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Money)


# --------------------------------------------------------------------------- IA e configurações

class AIConversation(TimestampMixin, Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))

    messages: Mapped[list[AIMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AIMessage.id")


class AIMessage(TimestampMixin, Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | model | tool
    content: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(40))
    tool_args: Mapped[dict | None] = mapped_column(JSON)
    tool_status: Mapped[str | None] = mapped_column(String(20))  # pendente | executada | recusada | erro
    tool_result: Mapped[str | None] = mapped_column(Text)

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")


class AIInsight(TimestampMixin, Base):
    """Texto gerado pela IA guardado para não repetir a chamada (economia de tokens)."""
    __tablename__ = "ai_insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(60))


class AIUsage(TimestampMixin, Base):
    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    purpose: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


class MealLog(TimestampMixin, Base):
    """Refeição marcada como consumida (com os totais congelados no momento do registro)."""
    __tablename__ = "meal_logs"
    __table_args__ = (Index("ix_meal_logs_profile_date", "profile_id", "eaten_on"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    meal_id: Mapped[int | None] = mapped_column(ForeignKey("meals.id", ondelete="SET NULL"))
    eaten_on: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(160))
    kcal: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float)
    carbs_g: Mapped[float] = mapped_column(Float)
    fat_g: Mapped[float] = mapped_column(Float)
