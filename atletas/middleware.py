from django.utils import timezone

from .models import Atleta


class SincronizarCategoriasAtletasMiddleware:
    """
    Sincroniza las categorías de los atletas cuando cambia
    el año calendario.

    Cada proceso del servidor realiza la comprobación una vez
    por año, por lo que no se consulta toda la tabla en cada
    petición.
    """

    def __init__(
        self,
        get_response,
    ):

        self.get_response = (
            get_response
        )

        self.anio_sincronizado = None


    def __call__(
        self,
        request,
    ):

        if request.user.is_authenticated:

            anio_actual = (
                timezone.localdate().year
            )


            if (
                self.anio_sincronizado
                != anio_actual
            ):

                Atleta.sincronizar_categorias(
                    anio_actual
                )

                self.anio_sincronizado = (
                    anio_actual
                )


        return self.get_response(
            request
        )