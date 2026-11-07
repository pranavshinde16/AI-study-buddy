from fastapi import APIRouter, status

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.schemas.errors import error_responses
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses=error_responses(409, 422),
)
def register(body: RegisterRequest, db: DbSession) -> UserOut:
    user = auth_service.register_user(db, body.email, body.password, body.full_name)
    return UserOut.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and get a JWT",
    responses=error_responses(401, 422),
)
def login(body: LoginRequest, db: DbSession, settings: AppSettings) -> TokenResponse:
    user = auth_service.authenticate(db, body.email, body.password)
    token, expires_in = create_access_token(str(user.id), settings.secret_key, settings.access_token_expire_minutes)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserOut, summary="Current user", responses=error_responses(401))
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
