"""Khung website Phone Shop - Task 6; chạy: flet run --web main.py."""

from decimal import Decimal, InvalidOperation

import flet as ft

from ui.components.money_format import format_vnd
from ui.components.notifications import notify
from ui.navigation import MENU, ROLE_LABELS, demo_route_visible, menu_for_role


def main(page: ft.Page) -> None:
    page.title = "Phone Shop | Khung website"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE)
    page.padding = 0

    # Chỉ mô phỏng 4 vai trò để kiểm tra MENU; chưa đăng nhập hoặc xác thực.
    current_role = "GUEST"

    def select_role(role: str) -> None:
        nonlocal current_role
        current_role = role
        # Chuyển về trang công khai để không giữ trang mẫu của vai trò trước.
        if page.route == "/":
            render_route()
        else:
            page.navigate("/")

    def role_selector() -> ft.Column:
        return ft.Column(
            controls=[
                ft.Text("Thử menu theo vai trò (CHỈ GIẢ LẬP UI):", weight=ft.FontWeight.BOLD),
                ft.Row(
                    wrap=True,
                    spacing=8,
                    controls=[
                        ft.Button(
                            label,
                            on_click=lambda e, chosen=role: select_role(chosen),
                        )
                        for role, label in ROLE_LABELS.items()
                    ],
                ),
                ft.Text(f"Vai trò mô phỏng hiện tại: {ROLE_LABELS[current_role]}"),
            ],
            spacing=8,
        )

    def nav_menu() -> ft.Column:
        links = menu_for_role(current_role)
        return ft.Column(
            controls=[
                ft.Text("MENU", weight=ft.FontWeight.BOLD),
                ft.Row(
                    wrap=True,
                    spacing=8,
                    run_spacing=8,
                    controls=[
                        ft.Button(
                            item.label,
                            on_click=lambda e, target=item.route: page.navigate(target),
                        )
                        for item in links
                    ],
                ),
            ],
            spacing=8,
        )

    def money_demo() -> ft.Column:
        amount = ft.TextField(
            label="Thử nhập giá (VND)", value="12500000.50", width=280,
        )
        result = ft.Text(f"Kết quả: {format_vnd(Decimal('12500000.50'))}")

        def convert(e) -> None:
            try:
                result.value = f"Kết quả: {format_vnd(amount.value or '')}"
                page.update()
                notify(page, "Đã định dạng giá tiền thành công!")
            except (InvalidOperation, ValueError, TypeError):
                notify(page, "Giá tiền không hợp lệ.", error=True)

        return ft.Column(
            controls=[
                ft.Text("THỬ ĐỊNH DẠNG VND", weight=ft.FontWeight.BOLD),
                ft.Text("Chỉ định dạng hiển thị, không ghi vào database."),
                amount,
                ft.Button("Định dạng VND", on_click=convert),
                result,
            ],
            spacing=8,
        )

    def content_for(route: str) -> ft.Column:
        known_routes = {item.route for item in MENU}
        if route not in known_routes:
            return ft.Column(
                controls=[ft.Text("404 – Không tìm thấy trang", size=24)],
            )

        if not demo_route_visible(current_role, route):
            return ft.Column(
                controls=[
                    ft.Text("Trang không có trong menu giả lập", size=22),
                    ft.Text("Bạn có thể thử vai trò khác trên trang chủ."),
                    ft.Text("Đây KHÔNG phải kiểm tra quyền bảo mật."),
                ],
            )

        title = next(item.label for item in MENU if item.route == route)
        items: list[ft.Control] = [
            ft.Text(title, size=25, weight=ft.FontWeight.BOLD),
            ft.Text("Giao diện khung: chức năng và dữ liệu thật sẽ làm ở Task tiếp theo."),
        ]
        if route == "/":
            items += [
                ft.Container(
                    content=ft.Text(
                        "Phone Shop • Website quản lý cửa hàng điện thoại • Task 6"
                    ),
                    padding=15,
                    border_radius=10,
                    bgcolor=ft.Colors.BLUE_50,
                ),
                money_demo(),
                ft.Button(
                    "Thông báo thành công",
                    on_click=lambda e: notify(page, "Đây là thông báo thành công!"),
                ),
                ft.Button(
                    "Thông báo lỗi",
                    on_click=lambda e: notify(page, "Đây là thông báo lỗi mẫu!", error=True),
                ),
            ]
        else:
            items.append(ft.Text("Chưa kết nối Service/Repository hoặc MariaDB."))
        return ft.Column(controls=items, spacing=12)

    def build_view(route: str) -> ft.View:
        return ft.View(
            route=route,
            controls=[
                ft.AppBar(
                    title=ft.Text("PHONE SHOP"),
                    bgcolor=ft.Colors.BLUE_100,
                    actions=[
                        ft.Button("Trang chủ", on_click=lambda e: page.navigate("/")),
                    ],
                ),
                ft.SafeArea(
                    expand=True,
                    content=ft.Column(
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                        spacing=16,
                        controls=[
                            ft.Container(content=role_selector(), padding=12),
                            ft.Divider(),
                            ft.Container(content=nav_menu(), padding=12),
                            ft.Divider(),
                            ft.Container(content=content_for(route), padding=12),
                        ],
                    ),
                ),
            ],
        )

    def render_route(e=None) -> None:
        route = page.route or "/"
        page.views.clear()
        page.views.append(build_view("/"))
        if route != "/":
            page.views.append(build_view(route))
        page.update()

    async def view_pop(e) -> None:
        if len(page.views) > 1:
            page.views.pop()
            await page.push_route(page.views[-1].route)

    page.on_route_change = render_route
    page.on_view_pop = view_pop
    render_route()


if __name__ == "__main__":
    ft.run(main)
