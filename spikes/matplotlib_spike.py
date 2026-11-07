
import flet as ft
import flet_charts as fch
import matplotlib.pyplot as plt


def main(page: ft.Page) -> None:
    page.title = "Phone Shop | MatplotlibChart"

    # Tạo dữ liệu thử nghiệm
    brands = [
        "Apple",
        "Samsung",
        "Xiaomi",
        "OPPO",
    ]

    units = [12, 9, 6, 4]

    # Khởi tạo Figure
    figure, ax = plt.subplots(
        figsize=(7, 4)
    )

    # Vẽ biểu đồ
    ax.bar(brands, units)

    ax.set_title("So luong ban thu nghiem")
    ax.set_xlabel("Hang dien thoai")
    ax.set_ylabel("So luong")

    figure.tight_layout()

    # Đưa MatplotlibChart lên giao diện Flet
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.Text(
                        "Task 4 - MatplotlibChart",
                        size=22,
                    ),
                    ft.Text(
                        "Du lieu thu nghiem - chua ket noi DB"
                    ),
                    fch.MatplotlibChart(
                        figure=figure,
                        expand=True,
                    ),
                ],
            ),
        )
    )


if __name__ == "__main__":
    ft.run(main)
