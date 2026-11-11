
"""Website Phone Shop - Flet Web.

Task 6: Khung UI và menu.
Task 11: Trang đăng ký.
Task 15: Đăng nhập, đăng xuất và điều hướng theo role.

Chạy: flet run --web main.py
"""

from decimal import Decimal, InvalidOperation

import flet as ft

from models.app_error import AppError
from services.auth_service import (
    AuthenticatedUser,
    AuthService,
    LoginResult,
)
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from ui.components.money_format import format_vnd
from ui.components.notifications import notify
from ui.navigation import (
    MENU,
    ROLE_LABELS,
    home_route_for_role,
    menu_for_role,
    route_available,
)
from ui.pages.catalog_page import build_catalog_page
from ui.pages.import_page import build_import_page
from ui.pages.inventory_page import build_inventory_page
from ui.pages.login_page import build_login_page
from ui.pages.product_management_page import build_product_management_page
from ui.pages.profile_page import build_profile_page
from ui.pages.register_page import build_register_page
from ui.route_guard import check_route_access


def main(page: ft.Page) -> None:
    page.title = "Phone Shop | Website quản lý điện thoại"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(
        color_scheme_seed=ft.Colors.BLUE
    )
    page.padding = 0

    auth_service = AuthService()
    # Task 21: FilePicker dùng chung trong trang hồ sơ.
    avatar_picker = ft.FilePicker()
    page.services.append(avatar_picker)
    known_routes = {
        item.route
        for item in MENU
    }

    def current_user() -> AuthenticatedUser | None:
        """Lấy danh tính hiện tại từ server session và DB."""

        session_store = page.session.store

        # Khách chưa đăng nhập: không cần truy vấn database.
        if session_store.get(AUTH_SESSION_USER_ID_KEY) is None:
            return None

        try:
            # Truy vấn lại role và ACTIVE từ MariaDB.
            return auth_service.require_user(
                session_store=session_store
            )

        except AppError as exc:
            # Task 14 đã xóa session khi ID sai,
            # user không tồn tại hoặc bị LOCKED.
            if exc.error_code in {
                "UNAUTHORIZED",
                "ACCOUNT_LOCKED",
            }:
                return None

            # Không che giấu lỗi nghiệp vụ khác.
            raise

    def login_success(result: LoginResult) -> None:
        """Đăng nhập thành công, điều hướng đúng role."""

        destination = home_route_for_role(result.role)

        # render_route sẽ xác thực lại user_id từ DB.
        page.navigate(destination)

        notify(
            page,
            f"Đăng nhập thành công. Xin chào {result.full_name}!",
        )

    def logout(e=None) -> None:
        """Đăng xuất và xóa dữ liệu phiên hiện tại."""

        auth_service.logout(
            session_store=page.session.store
        )

        page.navigate("/")
        notify(page, "Bạn đã đăng xuất thành công.")

    def account_header(
        user: AuthenticatedUser | None,
    ) -> ft.Row:
        """Thông tin tài khoản tại đầu website."""

        if user is None:
            return ft.Row(
                wrap=True,
                spacing=10,
                controls=[
                    ft.Text("Bạn đang truy cập với vai trò khách."),
                    ft.Button(
                        "Đăng nhập",
                        on_click=lambda e: page.navigate("/login"),
                    ),
                    ft.Button(
                        "Đăng ký",
                        on_click=lambda e: page.navigate("/register"),
                    ),
                ],
            )

        role_label = ROLE_LABELS.get(
            user.role,
            user.role,
        )

        return ft.Row(
            wrap=True,
            spacing=10,
            controls=[
                ft.Text(
                    f"Xin chào, {user.full_name} "
                    f"({role_label})",
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Button(
                    "Đăng xuất",
                    on_click=logout,
                ),
            ],
        )

    def nav_menu(
        user: AuthenticatedUser | None,
    ) -> ft.Column:
        """Menu dựa trên role thực, không có nút giả lập."""

        role = user.role if user is not None else "GUEST"
        links = menu_for_role(role)

        return ft.Column(
            controls=[
                ft.Text(
                    "MENU",
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Row(
                    wrap=True,
                    spacing=8,
                    run_spacing=8,
                    controls=[
                        ft.Button(
                            item.label,
                            on_click=(
                                lambda e, target=item.route:
                                page.navigate(target)
                            ),
                        )
                        for item in links
                    ],
                ),
            ],
            spacing=8,
        )

    def money_demo() -> ft.Column:
        """Giữ phần định dạng VND từ Task 6."""

        amount = ft.TextField(
            label="Thử nhập giá (VND)",
            value="12500000.50",
            width=280,
        )

        result = ft.Text(
            "Kết quả: "
            f"{format_vnd(Decimal('12500000.50'))}"
        )

        def convert(e) -> None:
            try:
                result.value = (
                    "Kết quả: "
                    f"{format_vnd(amount.value or '')}"
                )
                page.update()

                notify(
                    page,
                    "Đã định dạng giá tiền thành công!",
                )

            except (InvalidOperation, ValueError, TypeError):
                notify(
                    page,
                    "Giá tiền không hợp lệ.",
                    error=True,
                )

        return ft.Column(
            controls=[
                ft.Text(
                    "THỬ ĐỊNH DẠNG VND",
                    weight=ft.FontWeight.BOLD,
                ),
                amount,
                ft.Button(
                    "Định dạng VND",
                    on_click=convert,
                ),
                result,
            ],
            spacing=8,
        )

    def content_for(
        route: str,
        user: AuthenticatedUser | None,
    ) -> ft.Column:
        """Tạo nội dung trang sau khi kiểm tra route."""

        if route not in known_routes:
            return ft.Column(
                controls=[
                    ft.Text(
                        "404 – Không tìm thấy trang",
                        size=24,
                    )
                ],
            )

        role = user.role if user is not None else "GUEST"

        # Không render nội dung khi role không đủ quyền.
        if not route_available(role, route):
            return ft.Column(
                controls=[
                    ft.Text(
                        "403 – Không có quyền truy cập",
                        size=24,
                    ),
                    ft.Text(
                        "Tài khoản hiện tại không được "
                        "xem trang này."
                    ),
                ],
            )

        # Trang đăng nhập thật - Task 15
        if route == "/login":
            return build_login_page(
                page,
                on_success=login_success,
            )

        # Trang đăng ký thật - Task 11
        if route == "/register":
            return build_register_page(page)

        # Trang hồ sơ cá nhân thật - US03 Task 18.
        if route == "/profile":
            return build_profile_page(
                page,
                on_saved=render_route,
                file_picker=avatar_picker,
            )

        # Task 30 – Giao diện quản lý sản phẩm.
        # Đã đi qua Route Guard phía trên.
        if route == "/admin/products":
            return build_product_management_page(page)

        # Task 35 – US06: Hãng và nhà cung cấp.
        # Route Guard đã kiểm tra role phía trên.
        if route == "/admin/catalog":
            return build_catalog_page(page)

        # Task 40 – US07: Lập phiếu nhập và lịch sử nhập kho.
        if route == "/admin/imports":
            return build_import_page(page)

        # Task 40 – US07: Tồn kho và lịch sử biến động.
        if route == "/admin/inventory":
            return build_inventory_page(page)

        title = next(
            item.label
            for item in MENU
            if item.route == route
        )

        items: list[ft.Control] = [
            ft.Text(
                title,
                size=25,
                weight=ft.FontWeight.BOLD,
            ),
        ]

        if route == "/":
            items.extend(
                [
                    ft.Text(
                        "Chào mừng đến Phone Shop v2.5"
                    ),
                    ft.Container(
                        content=ft.Text(
                            "Website quản lý cửa hàng điện thoại"
                        ),
                        padding=15,
                        border_radius=10,
                        bgcolor=ft.Colors.BLUE_50,
                    ),
                    money_demo(),
                    ft.Button(
                        "Thông báo thành công",
                        on_click=lambda e: notify(
                            page,
                            "Đây là thông báo thành công!",
                        ),
                    ),
                    ft.Button(
                        "Thông báo lỗi",
                        on_click=lambda e: notify(
                            page,
                            "Đây là thông báo lỗi mẫu!",
                            error=True,
                        ),
                    ),
                ]
            )
        else:
            # Những trang nghiệp vụ thật sẽ được lập trình
            # trong các Task tương ứng.
            items.append(
                ft.Text(
                    "Đây là trang khung. "
                    "Chức năng nghiệp vụ sẽ được "
                    "hoàn thiện ở Task tiếp theo."
                )
            )

        return ft.Column(
            controls=items,
            spacing=12,
        )

    def build_view(
        route: str,
        user: AuthenticatedUser | None,
    ) -> ft.View:
        """Tạo View Flet từ route và danh tính thực."""

        return ft.View(
            route=route,
            controls=[
                ft.AppBar(
                    title=ft.Text("PHONE SHOP"),
                    bgcolor=ft.Colors.BLUE_100,
                    actions=[
                        ft.Button(
                            "Trang chủ",
                            on_click=lambda e: page.navigate("/"),
                        ),
                    ],
                ),
                ft.SafeArea(
                    expand=True,
                    content=ft.Column(
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                        spacing=16,
                        controls=[
                            ft.Container(
                                content=account_header(user),
                                padding=12,
                            ),
                            ft.Divider(),
                            ft.Container(
                                content=nav_menu(user),
                                padding=12,
                            ),
                            ft.Divider(),
                            ft.Container(
                                content=content_for(route, user),
                                padding=12,
                            ),
                        ],
                    ),
                ),
            ],
        )


    def render_route(e=None) -> None:
        """US04: kiểm tra quyền trước khi dựng màn hình.

        Danh tính và role phải được lấy từ MariaDB thông qua
        current_user() -> AuthService.require_user().
        """

        route = page.route or "/"

        # 1. Kiểm tra phiên và đọc lại role từ database.
        user = current_user()
        role = user.role if user is not None else "GUEST"

        # 2. Kiểm tra URL trước khi dựng View.
        decision = check_route_access(
            route=route,
            role=role,
        )

        # 3. Guest vào trang bảo vệ -> login.
        #    Đã đăng nhập vào login/register -> trang theo role.
        if decision.redirect_to is not None:
            page.navigate(decision.redirect_to)
            return

        # 4. Dựng lại View chỉ sau khi Route Guard kiểm tra.
        # content_for() hiện có vẫn hiển thị 403 hoặc 404
        # khi decision không phải ALLOW.
        page.views.clear()
        page.views.append(
            build_view("/", user)
        )

        if route != "/":
            page.views.append(
                build_view(route, user)
            )

        page.update()


    async def view_pop(e) -> None:
        """Xử lý nút Back của Flet."""

        if len(page.views) > 1:
            page.views.pop()
            await page.push_route(
                page.views[-1].route
            )

    page.on_route_change = render_route
    page.on_view_pop = view_pop

    render_route()



if __name__ == "__main__":
    ft.run(
        main,
        assets_dir="assets",
        route_url_strategy="hash",
    )
