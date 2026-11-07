
import flet as ft

SESSION_KEY = "spike_name"


def main(page: ft.Page) -> None:
    page.title = "Phone Shop | Flet Web Spike"

    # Trang nhập dữ liệu
    def make_form_view() -> ft.View:
        name_field = ft.TextField(
            label="Nhập tên thử nghiệm",
            width=350,
        )
        feedback = ft.Text("")

        def save_name(e):
            name = name_field.value.strip()

            if not name:
                feedback.value = "Vui lòng nhập tên."
                page.update()
                return

            # Lưu dữ liệu ở Session phía server
            page.session.store.set(
                SESSION_KEY,
                name,
            )

            page.navigate("/session")

        return ft.View(
            route="/form",
            controls=[
                ft.AppBar(
                    title=ft.Text("Kiểm tra Form")
                ),
                ft.SafeArea(
                    content=ft.Column(
                        controls=[
                            ft.Text("Nhập tên và lưu Session."),
                            name_field,
                            ft.Button(
                                "Lưu vào Session",
                                on_click=save_name,
                            ),
                            feedback,
                            ft.Button(
                                "Trang chủ",
                                on_click=lambda e: page.navigate("/"),
                            ),
                        ]
                    )
                ),
            ],
        )

    # Trang đọc dữ liệu Session
    def make_session_view() -> ft.View:
        saved = page.session.store.get(SESSION_KEY)

        display = (
            str(saved)
            if saved is not None
            else "(chưa có dữ liệu)"
        )

        return ft.View(
            route="/session",
            controls=[
                ft.AppBar(
                    title=ft.Text("Kiểm tra Session")
                ),
                ft.SafeArea(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                f"Giá trị đã lưu: {display}",
                                size=20,
                            ),
                            ft.Button(
                                "Nhập lại",
                                on_click=lambda e: page.navigate("/form"),
                            ),
                            ft.Button(
                                "Trang chủ",
                                on_click=lambda e: page.navigate("/"),
                            ),
                        ]
                    )
                ),
            ],
        )

    # Xử lý điều hướng
    def route_change(e=None):
        page.views.clear()

        # Trang chủ luôn tồn tại
        page.views.append(
            ft.View(
                route="/",
                controls=[
                    ft.AppBar(
                        title=ft.Text("Phone Shop")
                    ),
                    ft.SafeArea(
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    "Task 4 - Flet Web Spike",
                                    size=24,
                                ),
                                ft.Button(
                                    "Mở trang Form",
                                    on_click=lambda e: page.navigate("/form"),
                                ),
                                ft.Button(
                                    "Xem Session",
                                    on_click=lambda e: page.navigate("/session"),
                                ),
                            ]
                        )
                    ),
                ],
            )
        )

        if page.route == "/form":
            page.views.append(make_form_view())

        elif page.route == "/session":
            page.views.append(make_session_view())

        elif page.route not in ("/", ""):
            page.views.append(
                ft.View(
                    route=page.route,
                    controls=[
                        ft.AppBar(title=ft.Text("404")),
                        ft.Text("Không tìm thấy trang."),
                        ft.Button(
                            "Trang chủ",
                            on_click=lambda e: page.navigate("/"),
                        ),
                    ],
                )
            )

        page.update()

    # Nút Back của Flet
    async def view_pop(e):
        if len(page.views) > 1:
            page.views.pop()
            await page.push_route(
                page.views[-1].route
            )

    page.on_route_change = route_change
    page.on_view_pop = view_pop

    route_change()


if __name__ == "__main__":
    ft.run(main)
