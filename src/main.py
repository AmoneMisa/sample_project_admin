from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .routers import languages, translations, testimonials, headerMenu, users, auth, offerCards, contacts, footer, \
    featureCards, cleanup, services, serviceCategories, pdf
from .models.models import Base
from .db.session import engine
from .init_admin import init_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await init_admin()

    yield

    await engine.dispose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:80",
        "http://127.0.0.1:80",
        "http://localhost",
        "http://127.0.0.1",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(languages.router)
app.include_router(translations.router)
app.include_router(testimonials.router)
app.include_router(headerMenu.router)
app.include_router(users.router)
app.include_router(auth.router)
app.include_router(offerCards.router)
app.include_router(contacts.router)
app.include_router(footer.router)
app.include_router(featureCards.router)
app.include_router(cleanup.router)
app.include_router(services.router)
app.include_router(serviceCategories.router)