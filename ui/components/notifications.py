"""Thông báo giao diện theo API Flet 1.0.x."""

import flet as ft


def notify(page: ft.Page, message: str, *, error: bool = False) -> None:
    page.show_dialog(
        ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.RED_700 if error else ft.Colors.GREEN_700,
            show_close_icon=True,
        )
    )
